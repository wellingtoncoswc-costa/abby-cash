import json
from pathlib import Path

from sqlalchemy import select

from app.channels import registry
from app.channels.evolution import EvolutionAdapter, EvolutionClient
from app.channels.ingest import ingest
from app.domain.transactions.models import Transaction
from app.jobs.inbound import process_inbound
from tests.assistant.fakes import FakeAdapter, FakeParser, expense
from tests.assistant.test_conversation import nubank_default
from tests.factories import make_link, make_user

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "evolution"


class SentAdapter(EvolutionAdapter):
    def __init__(self) -> None:
        super().__init__(EvolutionClient("http://evo", "K", "abby"), "s")
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, external_user_id: str, text: str) -> None:
        self.sent.append((external_user_id, text))


async def test_whatsapp_message_end_to_end(session, monkeypatch):
    wa = SentAdapter()
    tg = FakeAdapter()
    monkeypatch.setitem(registry._adapters, "whatsapp_evolution", wa)
    monkeypatch.setitem(registry._adapters, "telegram", tg)
    ana = await make_user(session, "ana@x.com")
    await make_link(session, ana, "5511988887777", "whatsapp_evolution")
    await nubank_default(session, ana)
    parser = FakeParser(expense(4500, "Alimentação", merchant="Mercado"))
    msgs = wa.parse_event(json.loads((FIX / "text.json").read_text(encoding="utf-8")))
    ids: list = []

    async def enqueue(i) -> None:
        ids.append(i)

    assert await ingest(session, [msgs], enqueue) == 1
    await process_inbound({"parser": parser}, str(ids[0]))
    [tx] = list(await session.scalars(select(Transaction)))
    assert (tx.origin, tx.source_message_id, tx.amount_cents) == (
        "whatsapp_evolution", "3EB0A1", 4500,
    )  # fmt: skip
    assert wa.sent[0][0] == "5511988887777" and wa.sent[0][1].startswith("✅ R$ 45,00")
    assert tg.sent == []  # a resposta volta pelo canal de origem


async def test_unlinked_whatsapp_sender_gets_instructions_only(session, monkeypatch):
    wa = SentAdapter()
    monkeypatch.setitem(registry._adapters, "whatsapp_evolution", wa)
    msg = wa.parse_event(json.loads((FIX / "text.json").read_text(encoding="utf-8")))
    ids: list = []

    async def enqueue(i) -> None:
        ids.append(i)

    await ingest(session, [msg], enqueue)
    await process_inbound({}, str(ids[0]))
    assert len(wa.sent) == 1 and "vincul" in wa.sent[0][1].lower()
    assert list(await session.scalars(select(Transaction))) == []
