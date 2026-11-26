from datetime import date

import pytest
from fastapi import HTTPException

from app.domain.bills.recurrence import monthly
from app.domain.bills.service import create_bill
from app.domain.cards.service import register_card_purchase
from app.domain.loans.service import create_loan
from app.domain.projections.service import projections
from app.domain.recurring.service import create_item
from app.domain.transactions.service import create_transaction
from tests.factories import make_account, make_card, make_user

TODAY = date(2026, 11, 25)


async def _setup(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=1_000_000)
    return a, acc


async def test_month_sums_every_source_and_never_counts_twice(session):
    a, acc = await _setup(session)
    sp = a.default_space_id
    await create_item(  # salário fixo 5.000 dia 30
        session, actor_id=a.id, space_id=sp, type="income", description="Salário",
        amount_cents=500_000, account_id=acc.id, rule=monthly(30), starts_on=date(2026, 11, 1),
    )  # fmt: skip
    await create_item(  # aluguel fixo 1.500 dia 28
        session, actor_id=a.id, space_id=sp, type="expense", description="Aluguel",
        amount_cents=150_000, account_id=acc.id, rule=monthly(28), starts_on=date(2026, 11, 1),
    )  # fmt: skip
    await create_loan(  # financiamento 800 desde out, 12 parcelas: nov(1ª em aberto?) e seguintes
        session, actor_id=a.id, space_id=sp, kind="financing", name="Carro",
        installment_cents=80_000, installments_total=12, first_due_on=date(2026, 12, 10),
    )  # fmt: skip
    # conta avulsa em dez + duplicata do aluguel (mesmo nome/valor) que não deve contar
    await create_bill(
        session, actor_id=a.id, space_id=sp, description="Internet", amount_cents=10_000,
        due_on=date(2026, 12, 15),
    )  # fmt: skip
    await create_bill(
        session, actor_id=a.id, space_id=sp, description="aluguel", amount_cents=150_000,
        due_on=date(2026, 12, 28),
    )  # fmt: skip
    card = await make_card(session, a, sp, closing_day=10, due_day=20)
    await register_card_purchase(  # cai na fatura que vence 20/12
        session, actor_id=a.id, space_id=sp, card_id=card.id, amount_cents=30_000,
        occurred_on=date(2026, 11, 20),
    )  # fmt: skip
    p = await projections(session, viewer_id=a.id, space_id=sp, today=TODAY, months=6)
    nov, dez = p["months"][0], p["months"][1]
    assert (nov["income_fixed_cents"], nov["expense_fixed_cents"]) == (500_000, 150_000)
    assert dez["income_fixed_cents"] == 500_000 and dez["expense_fixed_cents"] == 150_000
    assert dez["expense_loans_cents"] == 80_000
    assert dez["expense_cards_cents"] == 30_000
    assert dez["expense_bills_cents"] == 10_000  # Internet; o "aluguel" duplicado não conta
    assert dez["net_committed_cents"] == 500_000 - 150_000 - 80_000 - 30_000 - 10_000
    assert dez["commitment_bp"] == (150_000 + 80_000 + 30_000 + 10_000) * 10_000 // 500_000
    assert [e["name"] for e in p["loans_ending"]] == ["Carro"]
    assert p["loans_ending"][0]["last_due_on"] == date(2027, 11, 10)
    bal = p["current_balance_cents"]
    assert nov["projected_balance_committed_cents"] == bal + nov["net_committed_cents"]
    assert dez["projected_balance_committed_cents"] == (
        nov["projected_balance_committed_cents"] + dez["net_committed_cents"]
    )  # fmt: skip


async def test_variable_estimate_uses_only_cash_items_and_prorates_current_month(session):
    a, acc = await _setup(session)
    sp = a.default_space_id

    async def tx(type_, cents, on, **kw):
        await create_transaction(
            session, actor_id=a.id, space_id=sp, type=type_, amount_cents=cents, occurred_on=on,
            account_id=acc.id, **kw,
        )  # fmt: skip

    for m in (8, 9, 10):  # 3 meses anteriores completos
        await tx("expense", 60_000, date(2026, m, 12))
        await tx("income", 30_000, date(2026, m, 15))
    await tx("expense", 999_999, date(2026, 7, 10))  # fora da janela de 3 meses
    p = await projections(session, viewer_id=a.id, space_id=sp, today=TODAY, months=6)
    dez = p["months"][1]
    assert (dez["expense_estimated_cents"], dez["income_estimated_cents"]) == (60_000, 30_000)
    nov = p["months"][0]  # 5 dias restantes de 30
    assert nov["expense_estimated_cents"] == 60_000 * 5 // 30
    assert dez["net_cents"] == dez["net_committed_cents"] + 30_000 - 60_000
    assert p["averages"]["estimated_expense_cents"] == 60_000


async def test_history_and_guards(session):
    a, acc = await _setup(session)
    sp = a.default_space_id
    await create_transaction(
        session, actor_id=a.id, space_id=sp, type="expense", amount_cents=7_000,
        occurred_on=date(2026, 11, 3), account_id=acc.id,
    )  # fmt: skip
    p = await projections(session, viewer_id=a.id, space_id=sp, today=TODAY, months=12)
    assert len(p["months"]) == 12 and len(p["history"]) == 12
    assert p["history"][-1]["month"] == "2026-11" and p["history"][-1]["expense_cents"] == 7_000
    assert p["history"][-1]["balance_cents"] == 1_000_000 - 7_000
    b = await make_user(session, "b@x.com")
    with pytest.raises(HTTPException) as e:
        await projections(session, viewer_id=b.id, space_id=sp, today=TODAY, months=6)
    assert e.value.status_code in (403, 404)
    with pytest.raises(Exception, match="invalid_months"):
        await projections(session, viewer_id=a.id, space_id=sp, today=TODAY, months=7)
