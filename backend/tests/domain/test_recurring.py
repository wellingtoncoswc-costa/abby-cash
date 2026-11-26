from datetime import date

import pytest
from fastapi import HTTPException

from app.domain.accounts.service import delete_account
from app.domain.bills.recurrence import monthly, yearly
from app.domain.errors import DomainError
from app.domain.recurring.service import (
    create_item,
    delete_item,
    list_items,
    occurrences,
    post_due,
    projection,
    update_item,
)
from app.domain.transactions.service import account_balance
from tests.factories import category_id, make_account, make_family, make_user

D = date(2026, 11, 25)


async def _item(session, user, acc, **kw):
    base = dict(
        actor_id=user.id, space_id=acc.space_id, type="expense", description="Aluguel",
        amount_cents=100_000, account_id=acc.id, rule=monthly(5), starts_on=date(2026, 11, 1),
    )  # fmt: skip
    return await create_item(session, **{**base, **kw})


async def test_create_validates_owner_account_period_and_category(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    acc = await make_account(session, a.default_space_id)
    other = await make_account(session, b.default_space_id)
    item = await _item(session, a, acc)
    assert item.rule == {"kind": "monthly", "day": 5, "month": None, "n": 1}
    with pytest.raises(HTTPException):  # conta de outro espaço
        await _item(session, a, other)
    with pytest.raises(DomainError, match="invalid_period"):
        await _item(session, a, acc, ends_on=date(2026, 10, 1))
    income_cat = await category_id(session, a.default_space_id, "Salário", "income")
    with pytest.raises(DomainError):  # categoria de receita em despesa
        await _item(session, a, acc, category_id=income_cat)
    fam = await make_family(session, a, b)
    facc = await make_account(session, fam.id)
    with pytest.raises(HTTPException) as e:  # membro que não é dono não cadastra
        await _item(session, b, facc, space_id=fam.id)
    assert e.value.status_code in (403, 404)


async def test_occurrences_monthly_short_month_yearly_and_bounds(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id)
    m31 = await _item(session, a, acc, rule=monthly(31), starts_on=date(2026, 1, 1))
    assert occurrences(m31, date(2026, 2, 1), date(2026, 4, 30)) == [
        date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)
    ]  # fmt: skip
    yr = await _item(session, a, acc, rule=yearly(3, 10), starts_on=date(2026, 1, 1))
    assert occurrences(yr, date(2026, 1, 1), date(2028, 12, 31)) == [
        date(2026, 3, 10), date(2027, 3, 10), date(2028, 3, 10)
    ]  # fmt: skip
    ended = await _item(session, a, acc, starts_on=date(2026, 1, 1), ends_on=date(2026, 3, 31))
    assert occurrences(ended, date(2026, 1, 1), date(2026, 12, 31)) == [
        date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)
    ]  # fmt: skip


async def test_post_due_is_idempotent_catches_up_and_moves_money(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=500_000)
    rent = await _item(session, a, acc, starts_on=date(2026, 9, 1))  # dia 5: set, out, nov
    assert await post_due(session, rent, D) == 3  # recupera as datas perdidas
    assert await post_due(session, rent, D) == 0  # nada novo
    assert await account_balance(session, acc.id) == 500_000 - 300_000
    salary = await _item(
        session, a, acc, type="income", description="Salário", amount_cents=400_000,
        rule=monthly(20), starts_on=date(2026, 11, 1),
    )  # fmt: skip
    assert await post_due(session, salary, D) == 1  # 20/11 já passou: lança
    assert await account_balance(session, acc.id) == 500_000 - 300_000 + 400_000


async def test_paused_and_ended_items_do_not_post(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id)
    item = await _item(session, a, acc, starts_on=date(2026, 10, 1))
    await update_item(
        session, actor_id=a.id, space_id=item.space_id, item_id=item.id, fields={"active": False}
    )
    rows = await list_items(session, viewer_id=a.id, space_id=item.space_id, today=D)
    assert rows[0]["next_due_on"] is None


async def test_projection_future_only_balance_and_upcoming(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp, name="Banco", initial=1_000_000)
    await _item(session, a, acc, rule=monthly(28), starts_on=date(2026, 11, 1))  # despesa 100k
    await _item(
        session, a, acc, type="income", description="Salário", amount_cents=400_000,
        rule=monthly(30), starts_on=date(2026, 11, 1),
    )  # fmt: skip
    await _item(
        session, a, acc, description="Passado", rule=monthly(2), starts_on=date(2026, 11, 1)
    )
    p = await projection(session, viewer_id=a.id, space_id=sp, today=D)
    nov, dez = p["months"][0], p["months"][1]
    assert (nov["income_cents"], nov["expense_cents"]) == (400_000, 100_000)  # dia 2 já passou
    assert nov["projected_balance_cents"] == 1_000_000 + 300_000
    assert (dez["income_cents"], dez["expense_cents"]) == (400_000, 200_000)
    assert dez["projected_balance_cents"] == 1_000_000 + 300_000 + 200_000
    assert len(p["months"]) == 6
    assert [(u["due_on"], u["account_name"]) for u in p["upcoming"]][0] == (
        date(2026, 11, 28),
        "Banco",
    )


async def test_account_in_use_and_delete_item(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id)
    item = await _item(session, a, acc)
    with pytest.raises(DomainError, match="account_in_use"):
        await delete_account(session, actor_id=a.id, account_id=acc.id)
    await delete_item(session, actor_id=a.id, space_id=item.space_id, item_id=item.id)
    await delete_account(session, actor_id=a.id, account_id=acc.id)


async def test_privacy_purge_removes_investments_and_recurring_items(session):
    from sqlalchemy import func, select

    from app.domain import privacy
    from app.domain.investments import service as inv_svc
    from app.domain.investments.models import Investment
    from app.domain.recurring.models import RecurringItem

    a = await make_user(session, "gone@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    await _item(session, a, acc)
    cdb = await inv_svc.create_investment(
        session, actor_id=a.id, space_id=a.default_space_id, kind="cdb", name="CDB",
        rate_type="fixed", rate_bp=1250, today=D,
    )  # fmt: skip
    await inv_svc.buy(
        session, actor_id=a.id, investment_id=cdb.id, account_id=acc.id, on=D,
        amount_cents=10_000, today=D,
    )  # fmt: skip
    await privacy.delete_account(session, a)
    await session.commit()
    for model in (RecurringItem, Investment):
        assert await session.scalar(select(func.count()).select_from(model)) == 0
