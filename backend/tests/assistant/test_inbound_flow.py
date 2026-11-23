import asyncio
from uuid import UUID

from sqlalchemy import func, select

from app.assistant.processor import UNLINKED
from app.domain.channels.linking import create_link_code
from app.domain.channels.models import ChannelLink, InboundMessage
from app.domain.transactions.models import Transaction
from app.jobs.inbound import process_inbound
from tests.factories import make_inbound, make_user


async def run(session, text, **kw) -> UUID:
    iid = await make_inbound(session, text, **kw)
    await process_inbound({}, str(iid))
    return iid


async def test_unlinked_sender_gets_instructions_only(session, adapter):
    await make_user(session, "ana@x.com")  # existe usuário, mas este chat não está vinculado
    iid = await run(session, "gastei 45 no mercado")
    assert adapter.sent == [("111", UNLINKED)]
    assert await session.scalar(select(func.count()).select_from(Transaction)) == 0
    assert await session.scalar(select(func.count()).select_from(ChannelLink)) == 0
    row = await session.get(InboundMessage, iid)
    assert row.status == "processed" and row.user_id is None


async def test_start_with_code_links_and_welcomes(session, adapter):
    ana = await make_user(session, "ana@x.com")
    code = await create_link_code(ana.id, "telegram")
    await run(session, f"/start {code}")
    assert "vinculado" in adapter.sent[0][1]
    link = await session.scalar(select(ChannelLink))
    assert link is not None and link.user_id == ana.id and link.external_user_id == "111"


async def test_bare_code_also_links_and_wrong_code_is_refused(session, adapter):
    ana = await make_user(session, "ana@x.com")
    code = await create_link_code(ana.id, "telegram")
    wrong = "000000" if code != "000000" else "000001"
    await run(session, wrong, msg_id=1)
    assert "inválido" in adapter.sent[-1][1]
    assert await session.scalar(select(func.count()).select_from(ChannelLink)) == 0
    await run(session, code, msg_id=2)
    assert "vinculado" in adapter.sent[-1][1]


async def test_same_inbound_is_processed_only_once(session, adapter):
    iid = await make_inbound(session, "oi")
    await asyncio.gather(*[process_inbound({}, str(iid)) for _ in range(4)])
    assert len(adapter.sent) == 1
