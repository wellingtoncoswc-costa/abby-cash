from datetime import date

import pytest
from sqlalchemy import select

from app.domain.bills.models import Bill
from app.domain.errors import DomainError
from app.domain.loans.service import cancel_loan, create_loan, loan_progress, update_loan
from app.domain.payments import pay_bill
from tests.factories import make_account, make_user


async def _loan(session, user, *, total=12, first=date(2026, 1, 31), **kw):
    return await create_loan(
        session, actor_id=user.id, space_id=user.default_space_id, kind="financing", name="Carro",
        installment_cents=100_000, installments_total=total, first_due_on=first, **kw,
    )  # fmt: skip


async def _bills(session, loan_id):
    q = select(Bill).where(Bill.loan_id == loan_id).order_by(Bill.installment_number)
    return list(await session.scalars(q))


async def test_end_of_month_installments_are_lazy_and_topped_up_on_payment(session):
    user = await make_user(session, "a@x.com")
    acc = await make_account(session, user.default_space_id, initial=1_000_000)
    loan = await _loan(session, user)
    bills = await _bills(session, loan.id)
    assert [(b.installment_number, b.due_on, b.description) for b in bills] == [
        (1, date(2026, 1, 31), "Carro (1/12)"),
        (2, date(2026, 2, 28), "Carro (2/12)"),
        (3, date(2026, 3, 31), "Carro (3/12)"),
    ]  # fmt: skip
    await pay_bill(
        session, actor_id=user.id, bill_id=bills[0].id, account_id=acc.id, paid_on=date(2026, 1, 30)
    )  # fmt: skip
    bills = await _bills(session, loan.id)
    assert [b.due_on for b in bills][3] == date(2026, 4, 30) and len(bills) == 4
    p = await loan_progress(session, loan)
    assert (p.paid_count, p.remaining_count, p.remaining_cents) == (1, 11, 1_100_000)
    assert (p.next_due_on, p.last_due_on, p.progress_pct) == (
        date(2026, 2, 28), date(2026, 12, 31), 8,
    )  # fmt: skip


async def test_480_installments_generate_only_three(session):
    user = await make_user(session, "a@x.com")
    loan = await _loan(session, user, total=480)
    assert len(await _bills(session, loan.id)) == 3
    p = await loan_progress(session, loan)
    assert (p.remaining_count, p.remaining_cents) == (480, 48_000_000)
    assert p.last_due_on == date(2065, 12, 31)
    for bad in (0, 481):
        with pytest.raises(DomainError, match="invalid_loan"):
            await _loan(session, user, total=bad)


async def test_single_installment_and_cancel_keeps_paid(session):
    user = await make_user(session, "a@x.com")
    acc = await make_account(session, user.default_space_id, initial=1_000_000)
    one = await _loan(session, user, total=1)
    assert len(await _bills(session, one.id)) == 1
    loan = await _loan(session, user)
    first = (await _bills(session, loan.id))[0]
    await pay_bill(session, actor_id=user.id, bill_id=first.id, account_id=acc.id,
                   paid_on=date(2026, 1, 30))  # fmt: skip
    await cancel_loan(session, actor_id=user.id, loan_id=loan.id)
    left = await _bills(session, loan.id)
    assert [(b.installment_number, b.status) for b in left] == [(1, "paid")]
    p = await loan_progress(session, loan)
    assert (p.paid_count, p.remaining_count, p.next_due_on) == (1, 0, None)


async def test_update_changes_only_unpaid_installments(session):
    user = await make_user(session, "a@x.com")
    acc = await make_account(session, user.default_space_id, initial=1_000_000)
    loan = await _loan(session, user)
    first = (await _bills(session, loan.id))[0]
    await pay_bill(session, actor_id=user.id, bill_id=first.id, account_id=acc.id,
                   paid_on=date(2026, 1, 30))  # fmt: skip
    await update_loan(session, actor_id=user.id, loan_id=loan.id,
                      fields={"name": "Moto", "installment_cents": 90_000})  # fmt: skip
    got = [(b.description, b.amount_cents) for b in await _bills(session, loan.id)]
    assert got[0] == ("Carro (1/12)", 100_000)
    assert got[1:] == [("Moto (2/12)", 90_000), ("Moto (3/12)", 90_000), ("Moto (4/12)", 90_000)]
