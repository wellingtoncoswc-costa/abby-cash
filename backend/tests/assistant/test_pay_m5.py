from datetime import date

from sqlalchemy import select

from app.domain.accounts.models import Account
from app.domain.bills.models import Bill
from app.domain.bills.service import create_bill
from app.domain.cards.service import register_card_purchase
from app.domain.transactions.models import Transaction
from app.jobs.bills import send_bill_reminders
from tests.assistant.fakes import intent
from tests.factories import TS, make_account, make_card


async def mk(session, ana, name: str, day: int = 30, cents: int = 10_000) -> Bill:
    return await create_bill(
        session, actor_id=ana.user.id, space_id=ana.user.default_space_id, description=name,
        amount_cents=cents, due_on=date(2026, 11, day),
    )  # fmt: skip


async def test_paguei_after_reminder(ana, session, parser):
    await mk(session, ana, "Luz", 26)
    other = await mk(session, ana, "Internet", 30)
    await send_bill_reminders({}, now=TS)  # Luz vence amanhã (25/11)
    assert "Amanhã vence: Luz" in ana.adapter.sent[-1][1]
    reply = await ana.say("paguei")  # sem lista: paga a lembrada
    assert reply.startswith("✅ Paguei R$ 100,00 · Luz")
    await session.refresh(other)
    assert other.status == "open"


async def test_paguei_none_pending(ana):
    assert await ana.say("paguei") == "Não encontrei contas em aberto."


async def test_paguei_multiple_lists_and_choose_2(ana, session):
    await mk(session, ana, "Luz", 28)
    await mk(session, ana, "Internet")
    assert (await ana.say("paguei")).startswith("Qual conta você pagou?")
    assert await ana.say("7") == "Responda com um dos números da lista."
    assert (await ana.say("2")).startswith("✅ Paguei R$ 100,00 · Internet")


async def test_paguei_cash_uses_wallet(ana, session, parser):
    await make_account(session, ana.user.default_space_id, name="Itaú")
    await mk(session, ana, "Luz")
    parser.add(intent("pagar_conta", description="luz", account_hint="no dinheiro"))
    reply = await ana.say("paguei a luz no dinheiro")
    assert reply.startswith("✅ Paguei R$ 100,00 · Luz · hoje · Carteira")
    tx = await session.scalar(select(Transaction).where(Transaction.bill_id.is_not(None)))
    assert tx is not None
    assert (await session.get(Account, tx.account_id)).type == "wallet"


async def test_partial_invoice_via_chat(ana, session, parser):
    sp = ana.user.default_space_id
    card = await make_card(session, ana.user, sp, name="Visa")
    await register_card_purchase(
        session, actor_id=ana.user.id, space_id=sp, card_id=card.id, amount_cents=100_000,
        occurred_on=date(2026, 11, 5),
    )  # fmt: skip
    await mk(session, ana, "Luz")
    parser.add(intent("pagar_conta", amount_cents=50_000))
    reply = await ana.say("paguei 500 da fatura")
    assert reply.startswith("✅ Paguei R$ 500,00 · Fatura Visa") and "Falta R$ 500,00." in reply
