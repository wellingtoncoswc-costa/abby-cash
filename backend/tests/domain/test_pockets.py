from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.domain.errors import DomainError
from app.domain.pockets.models import CdiRate, Pocket, PocketMovement, PocketYieldPosting
from app.domain.pockets.service import (
    accrue_all,
    accrue_pocket,
    create_pocket,
    delete_pocket,
    deposit,
    pocket_stats,
    withdraw,
)
from app.domain.transactions.models import Transaction
from app.domain.transactions.service import account_balance
from tests.factories import make_account, make_user

JAN = date(2026, 1, 5)


async def _setup(session, *, initial=100_000, cdi_bp=12_000):
    user = await make_user(session, "a@x.com")
    acc = await make_account(session, user.default_space_id, initial=initial)
    p = await create_pocket(
        session, actor_id=user.id, space_id=user.default_space_id, account_id=acc.id,
        name="Reserva", cdi_bp=cdi_bp,
    )  # fmt: skip
    p.created_at = datetime(2026, 1, 2, 15, tzinfo=UTC)
    await session.commit()
    return user, acc, p


async def _rates(session, **by_day):
    for d, pct in by_day.items():
        session.add(CdiRate(on_date=date(2026, 1, int(d[1:])), daily_pct=Decimal(pct)))
    await session.commit()


async def _accruals(session, pid):
    q = select(PocketMovement.ref_date, PocketMovement.amount_cents).where(
        PocketMovement.pocket_id == pid, PocketMovement.kind == "accrual"
    )
    return [tuple(r) for r in (await session.execute(q.order_by(PocketMovement.ref_date))).all()]


async def test_yield_compounds_daily_is_idempotent_and_skips_days_without_cdi(session):
    user, acc, p = await _setup(session)
    await deposit(session, actor_id=user.id, pocket_id=p.id, amount_cents=50_000, on=JAN)
    # 06 e 08 têm CDI; 07 (sem taxa) não rende; 02 é anterior ao depósito/criação (d <= criação)
    await _rates(session, d2="0.055131", d6="0.055131", d8="0.055131")
    assert await accrue_pocket(session, p, date(2026, 1, 31)) == 2
    assert await accrue_pocket(session, p, date(2026, 1, 31)) == 0  # idempotente
    # 50000 * 0,055131% * 120% = 33,0786 -> 33; dia 8 sobre 50033 -> 33,10 -> 33
    assert await _accruals(session, p.id) == [(date(2026, 1, 6), 33), (date(2026, 1, 8), 33)]
    await session.commit()
    st = await pocket_stats(session, p.id, date(2026, 1, 31))
    assert (st.balance, st.pending, st.month_yield) == (50_066, 66, 66)


async def test_rounding_is_half_even_in_decimal(session):
    user, acc, p = await _setup(session, cdi_bp=10_000)
    await deposit(session, actor_id=user.id, pocket_id=p.id, amount_cents=5_000, on=JAN)
    await _rates(session, d6="0.05")  # 5000 * 0,05% = 2,5 -> 2 (half-up daria 3)
    await accrue_pocket(session, p, date(2026, 1, 31))
    assert await _accruals(session, p.id) == [(date(2026, 1, 6), 2)]


async def test_available_excludes_pockets_and_deposit_above_is_409(session):
    user, acc, p = await _setup(session, initial=100_000)
    await deposit(session, actor_id=user.id, pocket_id=p.id, amount_cents=60_000, on=JAN)
    assert await account_balance(session, acc.id) == 100_000  # depósito não é lançamento
    assert await session.scalar(select(func.count()).select_from(Transaction)) == 0
    from app.domain.pockets.service import account_pockets_cents

    assert await account_pockets_cents(session, acc.id) == 60_000
    with pytest.raises(HTTPException) as e:
        await deposit(session, actor_id=user.id, pocket_id=p.id, amount_cents=40_001, on=JAN)
    assert (e.value.status_code, e.value.detail) == (409, "insufficient_available")
    await deposit(session, actor_id=user.id, pocket_id=p.id, amount_cents=40_000, on=JAN)


async def test_withdraw_posts_pending_yield_as_income_then_checks_balance(session):
    user, acc, p = await _setup(session)
    await deposit(session, actor_id=user.id, pocket_id=p.id, amount_cents=50_000, on=JAN)
    await _rates(session, d6="0.055131")
    await accrue_pocket(session, p, date(2026, 1, 31))
    await session.commit()
    with pytest.raises(DomainError, match="insufficient_balance"):
        await withdraw(session, actor_id=user.id, pocket_id=p.id, amount_cents=50_034)
    await withdraw(session, actor_id=user.id, pocket_id=p.id, amount_cents=50_033)  # inclui o 33
    tx = (await session.scalars(select(Transaction))).one()
    assert (tx.type, tx.amount_cents, tx.account_id) == ("income", 33, acc.id)
    assert tx.description == "Rendimento — Reserva" and tx.occurred_on == date(2026, 1, 6)
    st = await pocket_stats(session, p.id, date(2026, 1, 31))
    assert (st.balance, st.pending) == (0, 0)
    assert await account_balance(session, acc.id) == 100_033


async def test_monthly_posting_is_single_and_adjusts_late_days(session):
    user, acc, p = await _setup(session)
    await deposit(session, actor_id=user.id, pocket_id=p.id, amount_cents=50_000, on=JAN)
    await _rates(session, d6="0.055131", d7="0.055131")
    feb = date(2026, 2, 3)
    await accrue_all(session, p.id, date(2026, 1, 20))  # mês corrente: não lança
    assert await session.scalar(select(func.count()).select_from(Transaction)) == 0
    for _ in range(2):  # fechou o mês: lança uma vez só
        await accrue_all(session, p.id, feb)
    txs = list(await session.scalars(select(Transaction)))
    assert len(txs) == 1 and txs[0].amount_cents == 66 and txs[0].occurred_on == date(2026, 1, 7)
    cat = txs[0].category_id
    assert cat is not None
    assert await session.scalar(select(func.count()).select_from(PocketYieldPosting)) == 1
    # resgate no meio de um mês lança o que há; novo dia no mesmo mês ajusta a MESMA receita
    session.add(CdiRate(on_date=date(2026, 1, 9), daily_pct=Decimal("0.055131")))
    await session.commit()
    await accrue_all(session, p.id, feb)
    session.expire_all()
    txs = list(await session.scalars(select(Transaction)))
    assert len(txs) == 1 and txs[0].amount_cents == 99 and txs[0].occurred_on == date(2026, 1, 9)


async def test_delete_only_with_zero_balance_and_cdi_change_is_forward_only(session):
    user, acc, p = await _setup(session)
    await deposit(session, actor_id=user.id, pocket_id=p.id, amount_cents=1_000, on=JAN)
    with pytest.raises(DomainError, match="pocket_has_balance"):
        await delete_pocket(session, actor_id=user.id, pocket_id=p.id)
    await withdraw(session, actor_id=user.id, pocket_id=p.id, amount_cents=1_000)
    await delete_pocket(session, actor_id=user.id, pocket_id=p.id)
    assert (await session.get(Pocket, p.id)).closed_at is not None
    with pytest.raises(HTTPException):
        await deposit(session, actor_id=user.id, pocket_id=p.id, amount_cents=1, on=JAN)


async def test_backdated_move_before_last_accrual_is_rejected(session):
    user, acc, p = await _setup(session)
    await deposit(session, actor_id=user.id, pocket_id=p.id, amount_cents=1_000, on=JAN)
    await _rates(session, d6="0.05")
    await accrue_all(session, p.id, date(2026, 1, 31))
    with pytest.raises(DomainError, match="invalid_date"):
        await deposit(session, actor_id=user.id, pocket_id=p.id, amount_cents=10, on=JAN)
