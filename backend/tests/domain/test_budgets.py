from datetime import date

import pytest
from fastapi import HTTPException

from app.domain.bills.service import create_bill
from app.domain.budgets.service import (
    BudgetAlert,
    evaluate_thresholds,
    future_impact,
    month_spending,
    set_budget,
)
from app.domain.cards.service import register_card_purchase
from app.domain.errors import DomainError
from app.domain.goals.service import contribute, create_goal, withdraw
from app.domain.payments import pay_bill, pay_invoice
from app.domain.transactions.service import create_transaction
from tests.factories import category_id, make_account, make_card, make_family, make_user

NOV, DEC, JAN = date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1)


async def _spend(session, user, acc, amount, *, on=date(2026, 11, 10), cat=None, space=None):
    return await create_transaction(
        session, actor_id=user.id, space_id=space or user.default_space_id, type="expense",
        amount_cents=amount, occurred_on=on, account_id=acc.id, category_id=cat,
    )  # fmt: skip


async def _buy(session, user, card, amount, on, *, n=1, space=None):
    return await register_card_purchase(
        session, actor_id=user.id, space_id=space or user.default_space_id, card_id=card.id,
        amount_cents=amount, occurred_on=on, installments=n,
    )  # fmt: skip


async def test_card_installments_count_in_due_month(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp)
    card = await make_card(session, a, sp)  # fecha 10, vence 20
    await _buy(session, a, card, 30_000, date(2026, 11, 5), n=3)  # 10.000 em nov, dez e jan
    await _buy(session, a, card, 5_000, date(2026, 11, 15))  # depois do fechamento: fatura de dez
    await _spend(session, a, acc, 2_000, on=date(2026, 11, 3))  # à vista: mês da data
    await _spend(session, a, acc, 700, on=date(2026, 10, 31))
    assert await month_spending(session, sp, NOV) == 12_000
    assert await month_spending(session, sp, date(2026, 11, 17)) == 12_000  # qualquer dia do mês
    assert await month_spending(session, sp, DEC) == 15_000
    assert await month_spending(session, sp, JAN) == 10_000
    assert await month_spending(session, sp, date(2027, 2, 1)) == 0
    assert await month_spending(session, sp, date(2026, 10, 1)) == 700


async def test_invoice_payment_not_counted(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    card = await make_card(session, a, sp)
    (buy,) = await _buy(session, a, card, 30_000, date(2026, 11, 5))
    assert await month_spending(session, sp, NOV) == 30_000  # a compra conta (fatura vence em nov)
    await pay_invoice(
        session, actor_id=a.id, invoice_id=buy.invoice_id, account_id=acc.id,
        paid_on=date(2026, 11, 18), amount_cents=30_000,
    )  # fmt: skip
    assert await month_spending(session, sp, NOV) == 30_000  # o pagamento NÃO conta de novo


async def test_bill_payment_counts_on_payment_date(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    bill = await create_bill(
        session, actor_id=a.id, space_id=sp, description="Luz", amount_cents=9_000,
        due_on=date(2026, 11, 28),
    )  # fmt: skip
    await pay_bill(
        session, actor_id=a.id, bill_id=bill.id, account_id=acc.id, paid_on=date(2026, 12, 2)
    )  # fmt: skip
    assert await month_spending(session, sp, NOV) == 0
    assert await month_spending(session, sp, DEC) == 9_000


async def test_category_filter_in_month_spending(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp)
    mercado, lazer = await category_id(session, sp), await category_id(session, sp, "Lazer")
    await _spend(session, a, acc, 4_000, cat=mercado)
    await _spend(session, a, acc, 1_000, cat=lazer)
    assert await month_spending(session, sp, NOV) == 5_000
    assert await month_spending(session, sp, NOV, mercado) == 4_000


async def test_set_budget_validates_and_replaces_categories(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    sp = a.default_space_id
    mercado = await category_id(session, sp)
    with pytest.raises(DomainError, match="amount_must_be_positive"):
        await set_budget(session, actor_id=a.id, space_id=sp, month=NOV, limit_cents=0)
    with pytest.raises(DomainError, match="invalid_category"):
        await set_budget(
            session, actor_id=a.id, space_id=sp, month=NOV, limit_cents=100,
            categories={await category_id(session, b.default_space_id): 50},
        )  # fmt: skip
    with pytest.raises(HTTPException) as e:
        await set_budget(session, actor_id=b.id, space_id=sp, month=NOV, limit_cents=100)
    assert e.value.status_code == 404
    first = await set_budget(
        session, actor_id=a.id, space_id=sp, month=date(2026, 11, 17), limit_cents=100_000,
        categories={mercado: 40_000},
    )  # fmt: skip
    assert first.month == NOV  # normalizado para o dia 1
    again = await set_budget(session, actor_id=a.id, space_id=sp, month=NOV, limit_cents=90_000)
    assert again.id == first.id and again.limit_cents == 90_000  # mesmo mês: atualiza


async def test_alerts_fire_once_per_threshold(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp)
    await set_budget(session, actor_id=a.id, space_id=sp, month=NOV, limit_cents=100_000)
    await _spend(session, a, acc, 79_999)
    assert await evaluate_thresholds(session, sp, NOV) == []
    await _spend(session, a, acc, 1)  # 80.000 = 80%
    assert await evaluate_thresholds(session, sp, NOV) == [
        BudgetAlert("general", None, 80, 80_000, 100_000)
    ]
    assert await evaluate_thresholds(session, sp, NOV) == []  # não repete
    await _spend(session, a, acc, 20_000)  # 100.000 = 100%
    assert [x.threshold for x in await evaluate_thresholds(session, sp, NOV)] == [100]
    assert await evaluate_thresholds(session, sp, NOV) == []
    await _spend(session, a, acc, 1)  # acima do teto
    assert [x.threshold for x in await evaluate_thresholds(session, sp, NOV)] == [101]
    assert await evaluate_thresholds(session, sp, NOV) == []
    await _spend(session, a, acc, 5_000)
    assert await evaluate_thresholds(session, sp, NOV) == []  # "acima" só uma vez no mês


async def test_alert_jump_reports_only_highest_threshold(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp)
    await set_budget(session, actor_id=a.id, space_id=sp, month=NOV, limit_cents=100_000)
    await _spend(session, a, acc, 130_000)
    assert [x.threshold for x in await evaluate_thresholds(session, sp, NOV)] == [101]
    assert await evaluate_thresholds(session, sp, NOV) == []  # 80 e 100 também ficaram registrados


async def test_alerts_are_per_month_and_need_a_budget(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp)
    assert await evaluate_thresholds(session, sp, NOV) == []  # sem teto, sem alerta
    await set_budget(session, actor_id=a.id, space_id=sp, month=NOV, limit_cents=1_000)
    await set_budget(session, actor_id=a.id, space_id=sp, month=DEC, limit_cents=1_000)
    await _spend(session, a, acc, 900, on=date(2026, 11, 10))
    await _spend(session, a, acc, 900, on=date(2026, 12, 10))
    assert [x.threshold for x in await evaluate_thresholds(session, sp, NOV)] == [80]
    assert [x.threshold for x in await evaluate_thresholds(session, sp, DEC)] == [80]


async def test_category_budget_alert(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp)
    mercado, transporte = (
        await category_id(session, sp),
        await category_id(session, sp, "Transporte"),
    )
    await set_budget(
        session, actor_id=a.id, space_id=sp, month=NOV, limit_cents=1_000_000,
        categories={mercado: 10_000},
    )  # fmt: skip
    await _spend(session, a, acc, 50_000, cat=transporte)  # sem teto de categoria: nada
    assert await evaluate_thresholds(session, sp, NOV) == []
    await _spend(session, a, acc, 8_000, cat=mercado)
    assert await evaluate_thresholds(session, sp, NOV) == [
        BudgetAlert("category", mercado, 80, 8_000, 10_000)
    ]
    assert await evaluate_thresholds(session, sp, NOV) == []


async def test_personal_tx_not_in_family_budget(session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    acc = await make_account(session, fam.id, name="Conjunta")
    card = await make_card(session, w, fam.id)
    await _spend(session, w, acc, 30_000, space=fam.id)
    await _spend(session, w, acc, 20_000)  # #pessoal da w, na conta da família
    await _buy(session, w, card, 7_000, date(2026, 11, 5), space=fam.id)
    await _buy(session, w, card, 3_000, date(2026, 11, 6))  # #pessoal no cartão da família
    assert await month_spending(session, fam.id, NOV) == 37_000
    assert await month_spending(session, w.default_space_id, NOV) == 23_000
    assert await month_spending(session, h.default_space_id, NOV) == 0


async def test_future_impact_lists_due_months_with_limits(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    card = await make_card(session, a, sp)
    await set_budget(session, actor_id=a.id, space_id=sp, month=NOV, limit_cents=50_000)
    await set_budget(session, actor_id=a.id, space_id=sp, month=DEC, limit_cents=40_000)
    txs = await _buy(session, a, card, 30_000, date(2026, 11, 5), n=3)
    assert await future_impact(session, sp, txs) == [
        (NOV, 10_000, 50_000), (DEC, 10_000, 40_000), (JAN, 10_000, None),
    ]  # fmt: skip
    assert await future_impact(session, sp, []) == []


async def test_concurrent_evaluations_register_alert_once(session):
    import asyncio

    from app.core.db import SessionLocal

    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp)
    await set_budget(session, actor_id=a.id, space_id=sp, month=NOV, limit_cents=1_000)
    await _spend(session, a, acc, 900)

    async def run():
        async with SessionLocal() as s:
            return await evaluate_thresholds(s, sp, NOV)

    results = await asyncio.gather(*[run() for _ in range(5)])
    assert sum(len(r) for r in results) == 1


async def test_concurrent_first_set_budget_is_race_safe(session):
    import asyncio

    from sqlalchemy import func, select

    from app.core.db import SessionLocal
    from app.domain.budgets.models import Budget, BudgetCategory

    a = await make_user(session, "a@x.com")
    sp = a.default_space_id

    mercado, lazer = await category_id(session, sp), await category_id(session, sp, "Lazer")
    sets = [None, {mercado: 100}, {lazer: 200}, {mercado: 300, lazer: 400}, None]

    async def run(i):
        async with SessionLocal() as s:
            return await set_budget(
                s, actor_id=a.id, space_id=sp, month=NOV, limit_cents=1_000 + i, categories=sets[i]
            )

    await asyncio.gather(*[run(i) for i in range(5)])
    assert await session.scalar(select(func.count()).select_from(Budget)) == 1
    rows = (
        await session.execute(select(BudgetCategory.category_id, BudgetCategory.limit_cents))
    ).all()
    assert len(rows) == len({r[0] for r in rows})
    assert {r[0]: r[1] for r in rows} in [s or {} for s in sets]  # um conjunto consistente


async def test_goal_contribution_not_counted(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    goal = await create_goal(
        session, actor_id=a.id, space_id=sp, name="Viagem", target_cents=50_000,
        created_on=date(2026, 11, 1),
    )  # fmt: skip
    await contribute(
        session, actor_id=a.id, goal_id=goal.id, from_account_id=acc.id, amount_cents=20_000,
        on=date(2026, 11, 12),
    )  # fmt: skip
    await _spend(session, a, acc, 3_000)
    assert await month_spending(session, sp, NOV) == 3_000  # o aporte não conta
    await withdraw(
        session, actor_id=a.id, goal_id=goal.id, to_account_id=acc.id, amount_cents=5_000,
        on=date(2026, 11, 20),
    )  # fmt: skip
    assert await month_spending(session, sp, NOV) == 3_000  # a retirada também não
