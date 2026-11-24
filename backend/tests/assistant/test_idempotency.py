import asyncio
from datetime import date, timedelta

from sqlalchemy import func, select, update

from app.domain.channels.models import InboundMessage
from app.domain.transactions.models import Transaction
from app.jobs.inbound import process_inbound
from tests.assistant.fakes import expense, intent
from tests.factories import make_card, make_inbound


async def count(session) -> int:
    return await session.scalar(select(func.count()).select_from(Transaction))


async def crash_and_retry(session, chat, text: str, *, msg_id: int = 1) -> str:
    """Processa, devolve a mensagem a 'processing' parado (worker caiu antes de 'processed') e
    reprocessa; devolve a resposta da segunda vez."""
    iid = await make_inbound(session, text, ext=chat.ext, msg_id=msg_id)
    await process_inbound({"parser": chat.parser}, str(iid))
    await session.execute(
        update(InboundMessage)
        .where(InboundMessage.id == iid)
        .values(
            status="processing", text=text, updated_at=func.now() - timedelta(minutes=10)
        )  # o crash real não chegou a descartar o texto
    )
    await session.commit()
    before = len(chat.adapter.sent)
    await process_inbound({"parser": chat.parser}, str(iid))
    return "\n".join(t for _, t in chat.adapter.sent[before:])


async def test_retry_after_crash_does_not_duplicate_expense(ana, parser, session):
    parser.add(expense(4500, "Alimentação", merchant="Mercado"))
    reply = await crash_and_retry(session, ana, "gastei 45 no mercado")
    assert reply == "Já registrei isso."
    assert await count(session) == 1


async def test_retry_after_crash_does_not_duplicate_installments(ana, parser, session):
    card = await make_card(session, ana.user, ana.user.default_space_id, name="Visa")
    parser.add(intent("lancar_parcelado", amount_cents=30_000, installments=3, card_hint=card.name))
    assert await crash_and_retry(session, ana, "tv 300 em 3x no visa") == "Já registrei isso."
    assert await count(session) == 3


async def test_retry_after_crash_does_not_duplicate_aporte(ana, parser, session):
    from app.domain.goals.service import create_goal

    await create_goal(
        session, actor_id=ana.user.id, space_id=ana.user.default_space_id, name="Viagem",
        target_cents=500_000, created_on=date(2026, 11, 1),
    )  # fmt: skip
    parser.add(intent("aporte_meta", amount_cents=50_000, goal_hint="viagem"))
    assert await crash_and_retry(session, ana, "guardei 500 na viagem") == "Já registrei isso."
    assert await count(session) == 1


async def test_concurrent_replies_consume_the_pending_question_once(ana, parser, session):
    parser.add(expense(4500, "Alimentação", merchant="Mercado", confidence=0.4))
    assert "Posso lançar?" in await ana.say("gastei 45 no mercado")
    a = await make_inbound(session, "sim", ext=ana.ext, msg_id=10)
    b = await make_inbound(session, "sim", ext=ana.ext, msg_id=11)
    await asyncio.gather(
        process_inbound({"parser": parser}, str(a)), process_inbound({"parser": parser}, str(b))
    )
    assert await count(session) == 1


async def test_unique_index_catches_the_race_the_precheck_missed(ana, parser, session, monkeypatch):
    from app.assistant import processor

    async def never(t):
        return False

    monkeypatch.setattr(processor, "already_done", never)  # os dois workers passaram da checagem
    parser.add(expense(4500, "Alimentação"), expense(4500, "Alimentação"))
    assert await crash_and_retry(session, ana, "gastei 45") == "Já registrei isso."
    assert await count(session) == 1


async def test_two_replies_to_an_amount_question_write_once(ana, parser, session):
    parser.add(expense(None, "Mercado", merchant="Mercado"))
    assert (await ana.say("fui no mercado")).startswith("Quanto foi?")
    ids = [await make_inbound(session, "45", ext=ana.ext, msg_id=n) for n in (20, 21)]
    await asyncio.gather(*(process_inbound({"parser": parser}, str(i)) for i in ids))
    assert await count(session) == 1


async def test_correction_edits_the_transaction_from_when_it_was_asked(ana, parser, session):
    parser.add(expense(4500, "Mercado", merchant="Mercado"))
    await ana.say("gastei 45 no mercado")
    assert (await ana.say("corrigir")).startswith("O que está errado?")
    from app.domain.transactions.service import create_transaction

    wallet = await session.scalar(select(Transaction.account_id))
    await create_transaction(  # outro worker grava depois da pergunta (também pelo chat)
        session, actor_id=ana.user.id, space_id=ana.user.default_space_id, type="expense",
        amount_cents=1000, occurred_on=date(2026, 11, 25), description="x", merchant="Padaria",
        account_id=wallet, origin="telegram", source_message_id="111:99",
    )  # fmt: skip
    reply = await ana.say("valor 50")
    assert "Mercado" in reply
    amounts = sorted(
        (t.merchant, t.amount_cents) for t in await session.scalars(select(Transaction))
    )
    assert amounts == [("Mercado", 5000), ("Padaria", 1000)]


async def test_malformed_pending_state_is_discarded(ana, parser, session):
    from app.assistant.state import get_state, set_state
    from tests.factories import TS

    await set_state(session, ana.user.id, "telegram", "confirm", {}, TS)
    parser.add(expense(4500, "Mercado", merchant="Mercado"))
    assert (await ana.say("gastei 45 no mercado")).startswith("✅ R$ 45,00")
    assert await get_state(session, ana.user.id, "telegram", TS) is None
