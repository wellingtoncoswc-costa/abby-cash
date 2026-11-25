from datetime import date

from sqlalchemy import select

from app.domain.bills.service import create_bill
from app.domain.categories.models import CategoryRule
from app.domain.transactions.models import Transaction
from tests.assistant.fakes import expense, intent
from tests.assistant.test_conversation import nubank_default


async def test_expense_asks_account_even_with_default(ana, parser, session):
    await nubank_default(session, ana.user)
    parser.add(expense(4500, "Alimentação", merchant="Mercado"))
    assert (await ana.say("gastei 45 no mercado")).startswith("Em qual conta foi?")
    assert (await ana.say("nubank")).startswith(
        "✅ R$ 45,00 · Alimentação · Mercado · hoje · Conta Nubank"
    )


async def test_income_asks_where_it_entered(ana, parser, session):
    await nubank_default(session, ana.user)
    parser.add(intent("lancar_receita", "Salário", amount_cents=300_000))
    assert (await ana.say("recebi 3000 de salário")).startswith("Em qual conta entrou?")
    assert (await ana.say("nubank")).startswith("✅ R$ 3.000,00 · Salário · hoje · Conta Nubank")


async def test_unknown_category_asks_and_learns(ana, parser, session):
    parser.add(expense(4500, merchant="Padaria Boa"))
    reply = await ana.say("gastei 45 na padaria boa")
    assert reply.startswith("Qual a categoria?") and "Alimentação" in reply
    assert (await ana.say("alimentação")).startswith("✅ R$ 45,00 · Alimentação · Padaria Boa")
    assert await session.scalar(select(CategoryRule.id)) is not None
    parser.add(expense(1000, merchant="Padaria Boa"))
    assert (await ana.say("gastei 10 na padaria boa")).startswith("✅ R$ 10,00 · Alimentação")


async def test_pay_bill_asks_source_account(ana, session):
    await nubank_default(session, ana.user)
    await create_bill(
        session, actor_id=ana.user.id, space_id=ana.user.default_space_id, description="Luz",
        amount_cents=15_000, due_on=date(2026, 11, 30),
    )  # fmt: skip
    await ana.say("paguei")
    assert (await ana.say("sim")).startswith("De qual conta saiu?")
    assert (await ana.say("nubank")).startswith("✅ Paguei R$ 150,00 · Luz · hoje · Conta Nubank")
    assert await session.scalar(select(Transaction.id).where(Transaction.bill_id.is_not(None)))
