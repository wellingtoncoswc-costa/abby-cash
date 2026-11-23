from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.domain.accounts.access import use_account, visible_account
from app.domain.accounts.models import Account
from app.domain.bills.recurrence import (
    Recurrence,
    every_n_months,
    generate_occurrences,
    monthly,
    yearly,
)
from app.domain.bills.service import create_bill, list_bills
from app.domain.cards.service import invoice_remaining, register_card_purchase
from app.domain.errors import DomainError
from app.domain.payments import pay_bill, pay_invoice
from app.domain.transactions.models import Transaction
from app.domain.transactions.service import account_balance, list_transactions
from tests.factories import category_id, make_account, make_card, make_family, make_user

DUE = date(2026, 11, 20)


async def _bill(session, user, amount=12_000, **kw):
    return await create_bill(
        session, actor_id=user.id, space_id=user.default_space_id, description="Luz",
        amount_cents=amount, due_on=DUE, **kw,
    )  # fmt: skip


async def _tx_count(session) -> int:
    return int(await session.scalar(select(func.count()).select_from(Transaction)))


# ---- recorrência (pura) ----
def test_monthly_recurrence_day_31():
    assert generate_occurrences(monthly(31), date(2026, 1, 31)) == [
        date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30),
    ]  # fmt: skip
    assert generate_occurrences(monthly(31), date(2026, 1, 15)) == [
        date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31),
    ]  # fmt: skip
    assert date(2028, 2, 29) in generate_occurrences(monthly(31), date(2028, 1, 31))  # bissexto


def test_yearly_and_every_n_months():
    assert generate_occurrences(yearly(2, 29), date(2026, 1, 1), horizon_months=14) == [
        date(2026, 2, 28), date(2027, 2, 28),
    ]  # fmt: skip
    assert generate_occurrences(every_n_months(2, 15), date(2026, 1, 20), horizon_months=6) == [
        date(2026, 3, 15), date(2026, 5, 15), date(2026, 7, 15),
    ]  # fmt: skip


def test_invalid_recurrence_rules():
    for make in (
        lambda: every_n_months(121, 5), lambda: monthly(0), lambda: monthly(32),
        lambda: every_n_months(0, 5),
        lambda: yearly(13, 1), lambda: yearly(0, 1),
    ):  # fmt: skip
        with pytest.raises(DomainError, match="invalid_recurrence"):
            make()


def test_recurrence_json_roundtrip():
    rule = yearly(3, 10)
    assert Recurrence.from_json(rule.to_json()) == rule
    assert monthly(5).to_json() == {"kind": "monthly", "day": 5, "month": None, "n": 1}


# ---- contas a pagar ----
async def test_create_bill_validates_and_stores_recurrence(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    sp = a.default_space_id
    cat = await category_id(session, sp, "Contas da casa")
    bill = await _bill(
        session, a, category_id=cat, recurrence=monthly(31), responsible_user_id=a.id
    )
    assert (bill.kind, bill.status, bill.amount_cents) == ("manual", "open", 12_000)
    assert bill.recurrence_rule == {"kind": "monthly", "day": 31, "month": None, "n": 1}
    with pytest.raises(DomainError, match="amount_must_be_positive"):
        await _bill(session, a, amount=0)
    with pytest.raises(DomainError, match="invalid_category"):
        await _bill(session, a, category_id=await category_id(session, b.default_space_id))
    with pytest.raises(DomainError, match="invalid_responsible"):
        await _bill(session, a, responsible_user_id=b.id)
    with pytest.raises(HTTPException) as e:
        await create_bill(
            session, actor_id=b.id, space_id=sp, description="x", amount_cents=1, due_on=DUE
        )  # fmt: skip
    assert e.value.status_code == 404
    assert [x.id for x in await list_bills(session, viewer_id=a.id, space_id=sp)] == [bill.id]
    assert await list_bills(session, viewer_id=a.id, space_id=sp, status="paid") == []


async def test_pay_bill_creates_expense_on_account(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    cat = await category_id(session, a.default_space_id, "Contas da casa")
    bill = await _bill(session, a, category_id=cat)
    tx = await pay_bill(
        session, actor_id=a.id, bill_id=bill.id, account_id=acc.id, paid_on=date(2026, 11, 18)
    )  # fmt: skip
    assert (tx.type, tx.amount_cents, tx.account_id) == ("expense", 12_000, acc.id)
    assert (tx.category_id, tx.space_id, tx.bill_id) == (cat, bill.space_id, bill.id)
    assert tx.occurred_on == date(2026, 11, 18) and tx.created_by == a.id
    await session.refresh(bill)
    assert bill.status == "paid"
    assert await account_balance(session, acc.id) == 88_000


async def test_pay_bill_from_wallet(session):
    a = await make_user(session, "a@x.com")
    wallet = await session.scalar(
        select(Account).where(Account.space_id == a.default_space_id, Account.type == "wallet")
    )
    bill = await _bill(session, a)
    tx = await pay_bill(
        session, actor_id=a.id, bill_id=bill.id, account_id=wallet.id, paid_on=DUE
    )  # fmt: skip
    assert tx.account_id == wallet.id
    assert await account_balance(session, wallet.id) == -12_000


async def test_paying_requires_source_account(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id)
    (buy,) = await register_card_purchase(
        session, actor_id=a.id, space_id=a.default_space_id, card_id=card.id,
        amount_cents=5_000, occurred_on=date(2026, 11, 5),
    )  # fmt: skip
    bill = await _bill(session, a)
    with pytest.raises(DomainError, match="source_account_required"):
        await pay_bill(session, actor_id=a.id, bill_id=bill.id, account_id=None, paid_on=DUE)
    with pytest.raises(DomainError, match="source_account_required"):
        await pay_invoice(
            session, actor_id=a.id, invoice_id=buy.invoice_id, account_id=None, paid_on=DUE,
            amount_cents=5_000,
        )  # fmt: skip
    assert await _tx_count(session) == 1  # só a compra; nenhum pagamento sem origem


async def test_partial_bill_payment_and_invalid_amounts(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    bill = await _bill(session, a)
    await pay_bill(
        session, actor_id=a.id, bill_id=bill.id, account_id=acc.id, paid_on=DUE, amount_cents=5_000
    )  # fmt: skip
    await session.refresh(bill)
    assert bill.status == "partial"
    for bad in (0, 7_001):
        with pytest.raises(DomainError, match="invalid_payment_amount"):
            await pay_bill(
                session, actor_id=a.id, bill_id=bill.id, account_id=acc.id, paid_on=DUE,
                amount_cents=bad,
            )  # fmt: skip
    rest = await pay_bill(session, actor_id=a.id, bill_id=bill.id, account_id=acc.id, paid_on=DUE)
    assert rest.amount_cents == 7_000  # sem valor: quita o que falta
    await session.refresh(bill)
    assert bill.status == "paid"
    with pytest.raises(DomainError, match="invalid_payment_amount"):  # já quitada
        await pay_bill(session, actor_id=a.id, bill_id=bill.id, account_id=acc.id, paid_on=DUE)


async def test_pay_bill_access_rules(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    mine = await make_account(session, a.default_space_id)
    theirs = await make_account(session, b.default_space_id)
    bill = await _bill(session, a)
    with pytest.raises(HTTPException) as e:  # b não é membro do espaço da conta a pagar
        await pay_bill(session, actor_id=b.id, bill_id=bill.id, account_id=theirs.id, paid_on=DUE)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:  # a não pode debitar de conta do b
        await pay_bill(session, actor_id=a.id, bill_id=bill.id, account_id=theirs.id, paid_on=DUE)
    assert e.value.status_code == 403
    await pay_bill(session, actor_id=a.id, bill_id=bill.id, account_id=mine.id, paid_on=DUE)


async def _invoice_setup(session, amount=30_000):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    card = await make_card(session, a, a.default_space_id)
    (buy,) = await register_card_purchase(
        session, actor_id=a.id, space_id=a.default_space_id, card_id=card.id,
        amount_cents=amount, occurred_on=date(2026, 11, 5),
    )  # fmt: skip
    return a, acc, card, buy.invoice_id


async def test_pay_invoice_is_transfer_not_expense(session):
    a, acc, card, inv_id = await _invoice_setup(session)
    pay = await pay_invoice(
        session, actor_id=a.id, invoice_id=inv_id, account_id=acc.id, paid_on=date(2026, 11, 18),
        amount_cents=30_000,
    )  # fmt: skip
    assert pay.type == "transfer"
    assert (pay.account_id, pay.card_id, pay.invoice_id) == (acc.id, card.id, inv_id)
    assert pay.counter_account_id is None and pay.bill_id is not None
    assert await account_balance(session, acc.id) == 70_000
    assert await invoice_remaining(session, inv_id) == 0


async def test_partial_invoice_payment_leaves_remaining(session):
    from app.domain.bills.models import Bill

    a, acc, card, inv_id = await _invoice_setup(session)
    pay = lambda amount: pay_invoice(  # noqa: E731
        session, actor_id=a.id, invoice_id=inv_id, account_id=acc.id, paid_on=DUE,
        amount_cents=amount,
    )  # fmt: skip
    await pay(10_000)
    bill = await session.scalar(select(Bill).where(Bill.invoice_id == inv_id))
    assert await invoice_remaining(session, inv_id) == 20_000 and bill.status == "partial"
    for bad in (0, 20_001):
        with pytest.raises(DomainError, match="invalid_payment_amount"):
            await pay(bad)
    await pay(20_000)
    await session.refresh(bill)
    assert await invoice_remaining(session, inv_id) == 0 and bill.status == "paid"
    with pytest.raises(DomainError, match="invalid_payment_amount"):
        await pay(1)


async def test_purchase_after_payment_reopens_invoice(session):
    from app.domain.bills.models import Bill

    a, acc, card, inv_id = await _invoice_setup(session)
    await pay_invoice(
        session, actor_id=a.id, invoice_id=inv_id, account_id=acc.id, paid_on=DUE,
        amount_cents=30_000,
    )  # fmt: skip
    await register_card_purchase(
        session, actor_id=a.id, space_id=a.default_space_id, card_id=card.id,
        amount_cents=5_000, occurred_on=date(2026, 11, 8),
    )  # fmt: skip
    bill = await session.scalar(select(Bill).where(Bill.invoice_id == inv_id))
    await session.refresh(bill)
    assert (bill.amount_cents, bill.status) == (35_000, "partial")
    assert await invoice_remaining(session, inv_id) == 5_000


async def test_invoice_paid_from_personal_account_stays_in_payer_space(session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    card = await make_card(session, w, fam.id)
    mine = await make_account(session, w.default_space_id, name="Itaú pessoal", initial=50_000)
    (buy,) = await register_card_purchase(
        session, actor_id=w.id, space_id=fam.id, card_id=card.id, amount_cents=8_000,
        occurred_on=date(2026, 11, 5),
    )  # fmt: skip
    pay = await pay_invoice(
        session, actor_id=w.id, invoice_id=buy.invoice_id, account_id=mine.id, paid_on=DUE,
        amount_cents=8_000,
    )  # fmt: skip
    assert pay.space_id == w.default_space_id  # a conta pessoal não aparece para a família
    seen_by_h = await list_transactions(session, viewer_id=h.id, space_id=fam.id)
    assert pay.id not in [t.id for t in seen_by_h]
    assert await invoice_remaining(session, buy.invoice_id) == 0
    with pytest.raises(HTTPException) as e:  # h não pode debitar da conta pessoal da w
        await pay_invoice(
            session, actor_id=h.id, invoice_id=buy.invoice_id, account_id=mine.id, paid_on=DUE,
            amount_cents=1,
        )  # fmt: skip
    assert e.value.status_code == 403


async def test_pay_invoice_by_non_member_is_404(session):
    a, acc, card, inv_id = await _invoice_setup(session)
    b = await make_user(session, "b@x.com")
    theirs = await make_account(session, b.default_space_id)
    with pytest.raises(HTTPException) as e:
        await pay_invoice(
            session, actor_id=b.id, invoice_id=inv_id, account_id=theirs.id, paid_on=DUE,
            amount_cents=100,
        )  # fmt: skip
    assert e.value.status_code == 404


async def test_concurrent_payments_do_not_double_pay(session):
    import asyncio

    from app.core.db import SessionLocal

    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    bill = await _bill(session, a)
    _, _, _, inv_id = await _invoice_setup_for(session, a, acc)

    async def go(fn, **kw):
        async with SessionLocal() as s:
            try:
                return await fn(s, actor_id=a.id, account_id=acc.id, paid_on=DUE, **kw)
            except DomainError as e:
                return e

    bills = await asyncio.gather(*(go(pay_bill, bill_id=bill.id) for _ in range(4)))
    assert sum(isinstance(r, Transaction) for r in bills) == 1
    invs = await asyncio.gather(
        *(go(pay_invoice, invoice_id=inv_id, amount_cents=30_000) for _ in range(4))
    )
    assert sum(isinstance(r, Transaction) for r in invs) == 1
    assert await invoice_remaining(session, inv_id) == 0
    assert await account_balance(session, acc.id) == 100_000 - 12_000 - 30_000


async def _invoice_setup_for(session, a, acc):
    card = await make_card(session, a, a.default_space_id)
    (buy,) = await register_card_purchase(
        session, actor_id=a.id, space_id=a.default_space_id, card_id=card.id,
        amount_cents=30_000, occurred_on=date(2026, 11, 5),
    )  # fmt: skip
    return a, acc, card, buy.invoice_id


async def test_family_bill_paid_from_personal_account_stays_in_family_space(session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    mine = await make_account(session, w.default_space_id, name="Itaú pessoal", initial=50_000)
    bill = await create_bill(
        session, actor_id=w.id, space_id=fam.id, description="Luz", amount_cents=12_000, due_on=DUE
    )  # fmt: skip
    tx = await pay_bill(
        session, actor_id=w.id, bill_id=bill.id, account_id=mine.id, paid_on=DUE
    )  # fmt: skip
    assert (tx.space_id, tx.account_id) == (fam.id, mine.id)  # conta no orçamento da família
    assert await account_balance(session, mine.id) == 38_000
    seen_by_h = await list_transactions(session, viewer_id=h.id, space_id=fam.id)
    assert tx.id in [t.id for t in seen_by_h]
    with pytest.raises(HTTPException) as e:  # h não vê nem usa a conta pessoal da w
        await use_account(session, h.id, mine.id)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        await visible_account(session, h.id, mine.id)
    assert e.value.status_code == 404


async def test_non_member_pay_bill_404_does_not_hold_bill_lock(session):
    import asyncio

    from app.core.db import SessionLocal

    a, x = await make_user(session, "a@x.com"), await make_user(session, "x@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    acc_x = await make_account(session, x.default_space_id)
    bill = await _bill(session, a)
    async with SessionLocal() as outsider:  # mantém a transação aberta após o 404
        with pytest.raises(HTTPException) as e:
            await pay_bill(
                outsider, actor_id=x.id, bill_id=bill.id, account_id=acc_x.id, paid_on=DUE
            )
        assert e.value.status_code == 404
        async with SessionLocal() as legit:
            tx = await asyncio.wait_for(
                pay_bill(legit, actor_id=a.id, bill_id=bill.id, account_id=acc.id, paid_on=DUE),
                5,
            )
        assert tx.amount_cents == 12_000
