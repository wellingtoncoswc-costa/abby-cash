from datetime import date

import pytest
from fastapi import HTTPException

from app.domain.accounts.panel import account_panel
from app.domain.goals.service import create_goal
from app.domain.pockets.service import create_pocket, deposit
from app.domain.transactions.service import create_transaction
from tests.factories import category_id, make_account, make_user

NOV = date(2026, 11, 1)


async def _tx(session, user, acc, type_, cents, on, cat=None, desc="x", counter=None):
    return await create_transaction(
        session, actor_id=user.id, space_id=acc.space_id, type=type_, amount_cents=cents,
        occurred_on=on, account_id=acc.id, category_id=cat, description=desc,
        counter_account_id=counter,
    )  # fmt: skip


async def test_panel_month_totals_categories_pockets_goals(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    other = await make_account(session, sp, name="Outra", initial=0)
    mercado = await category_id(session, sp, "Mercado")
    salario = await category_id(session, sp, "Salário", "income")
    await _tx(session, a, acc, "income", 500_000, date(2026, 11, 5), salario, "Salário")
    await _tx(session, a, acc, "expense", 30_000, date(2026, 11, 6), mercado, "Mercado")
    await _tx(session, a, acc, "expense", 10_000, date(2026, 11, 7), mercado, "Feira")
    await _tx(session, a, acc, "transfer", 20_000, date(2026, 11, 8), None, "p/ outra", other.id)
    await _tx(session, a, acc, "expense", 99_000, date(2026, 10, 30), mercado, "mês anterior")
    pk = await create_pocket(
        session, actor_id=a.id, space_id=sp, account_id=acc.id, name="Reserva", cdi_bp=10000
    )
    await deposit(
        session, actor_id=a.id, pocket_id=pk.id, amount_cents=15_000, on=date(2026, 11, 9)
    )
    goal = await create_goal(
        session, actor_id=a.id, space_id=sp, name="Viagem", target_cents=100_000,
        created_on=NOV, account_ids=[acc.id],
    )  # fmt: skip
    p = await account_panel(session, a.id, acc.id, month=NOV, today=date(2026, 11, 20))
    assert (p["income_cents"], p["expense_cents"]) == (500_000, 40_000)
    assert p["transfer_net_cents"] == -20_000
    assert p["by_category"] == [{"category_id": mercado, "total_cents": 40_000}]
    assert [r["description"] for r in p["recent"]][:2] == ["p/ outra", "Feira"]
    assert [(x["id"], x["balance_cents"]) for x in p["pockets"]] == [(pk.id, 15_000)]
    assert [g["id"] for g in p["goals"]] == [goal.id] and p["is_default"] is False


async def test_panel_guards_access(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    acc = await make_account(session, a.default_space_id)
    with pytest.raises(HTTPException) as e:
        await account_panel(session, b.id, acc.id, month=NOV, today=NOV)
    assert e.value.status_code in (403, 404)
