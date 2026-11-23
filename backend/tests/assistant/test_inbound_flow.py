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


async def test_stale_processing_is_retaken_fresh_is_not(session, adapter):
    from sqlalchemy import text as sql

    stale = await make_inbound(session, "oi", msg_id=1)
    fresh = await make_inbound(session, "oi", msg_id=2)
    await session.execute(sql("update inbound_messages set status='processing'"))
    await session.execute(
        sql("update inbound_messages set updated_at = now() - interval '6 minutes' where id=:i"),
        {"i": stale},
    )
    await session.commit()
    await process_inbound({}, str(stale))
    await process_inbound({}, str(fresh))
    assert len(adapter.sent) == 1
    session.expire_all()
    assert (await session.get(InboundMessage, stale)).status == "processed"
    assert (await session.get(InboundMessage, fresh)).status == "processing"


async def test_non_ascii_digits_are_not_a_code(session, adapter):
    from app.core.redis import redis

    await run(session, "٠١٢٣٤٥")  # Arabic-Indic digits
    assert adapter.sent == [("111", UNLINKED)]
    assert await redis.get("link_fails:global") is None
    assert await redis.get("link_fails:telegram:111") is None


async def test_start_payload_uppercase_and_extra_spaces(session, adapter):
    ana = await make_user(session, "ana@x.com")
    code = await create_link_code(ana.id, "telegram")
    await run(session, f"  /START   {code}  ")
    assert "vinculado" in adapter.sent[0][1]
