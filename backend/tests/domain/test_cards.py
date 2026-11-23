from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.dates import to_local_date
from app.domain.bills.models import Bill
from app.domain.cards.billing import InvoiceDates, invoice_dates_for_purchase, split_installments
from app.domain.cards.models import Invoice
from app.domain.cards.service import (
    invoice_statement,
    invoice_total,
    register_card_purchase,
    use_card,
    visible_invoice,
)
from app.domain.errors import DomainError
from app.domain.spaces.service import remove_member
from app.domain.transactions.service import create_transaction
from tests.factories import make_card, make_family, make_user


def _inv(closing, due):
    return InvoiceDates(closing, due)


# ---- datas de fechamento (puras) ----
def test_purchase_on_closing_day_goes_to_current_invoice():
    expected = _inv(date(2026, 3, 10), date(2026, 3, 20))
    assert invoice_dates_for_purchase(10, 20, date(2026, 3, 10)) == expected
    assert invoice_dates_for_purchase(10, 20, date(2026, 3, 1)) == expected


def test_purchase_after_closing_goes_to_next():
    assert invoice_dates_for_purchase(10, 20, date(2026, 3, 11)) == _inv(
        date(2026, 4, 10), date(2026, 4, 20)
    )
    # vencimento "antes" do fechamento no calendário: 1º due_day depois do fechamento
    assert invoice_dates_for_purchase(25, 5, date(2026, 12, 26)) == _inv(
        date(2027, 1, 25), date(2027, 2, 5)
    )
    assert invoice_dates_for_purchase(25, 5, date(2026, 12, 25)) == _inv(
        date(2026, 12, 25), date(2027, 1, 5)
    )


def test_closing_day_31_in_february():
    assert invoice_dates_for_purchase(31, 10, date(2026, 2, 28)) == _inv(
        date(2026, 2, 28), date(2026, 3, 10)
    )  # fevereiro fecha no dia 28 (último dia do mês)
    assert invoice_dates_for_purchase(31, 10, date(2026, 3, 1)) == _inv(
        date(2026, 3, 31), date(2026, 4, 10)
    )
    assert invoice_dates_for_purchase(31, 10, date(2028, 2, 29)) == _inv(
        date(2028, 2, 29), date(2028, 3, 10)
    )  # ano bissexto


def test_closing_day_31_in_april():
    assert invoice_dates_for_purchase(31, 10, date(2026, 4, 30)) == _inv(
        date(2026, 4, 30), date(2026, 5, 10)
    )
    assert invoice_dates_for_purchase(31, 10, date(2026, 5, 1)) == _inv(
        date(2026, 5, 31), date(2026, 6, 10)
    )


def test_due_day_31_is_clamped_to_month_end():
    assert invoice_dates_for_purchase(10, 31, date(2026, 2, 5)) == _inv(
        date(2026, 2, 10), date(2026, 2, 28)
    )


def test_purchase_2330_local_uses_local_date():
    instant = datetime(2026, 3, 11, 2, 30, tzinfo=UTC)  # 23:30 de 10/03 em São Paulo
    local = to_local_date(instant, "America/Sao_Paulo")
    assert invoice_dates_for_purchase(10, 20, local).closing == date(2026, 3, 10)
    # usar o dia UTC jogaria a compra na fatura seguinte (o bug que o teste previne)
    assert invoice_dates_for_purchase(10, 20, instant.date()).closing == date(2026, 4, 10)


def test_split_600_in_3():
    assert split_installments(600, 3) == [200, 200, 200]


def test_split_1000_in_3():
    assert split_installments(1000, 3) == [334, 333, 333]


def test_split_edge_cases():
    assert split_installments(999, 1) == [999]
    with pytest.raises(DomainError, match="invalid_installments"):
        split_installments(1000, 0)
    with pytest.raises(DomainError, match="amount_too_small"):
        split_installments(2, 3)


# ---- faturas e parcelas (banco) ----
async def _buy(session, user, card, amount, on, *, n=1, space=None, desc="compra"):
    return await register_card_purchase(
        session, actor_id=user.id, space_id=space or user.default_space_id, card_id=card.id,
        amount_cents=amount, occurred_on=on, installments=n, description=desc,
    )  # fmt: skip


async def _invoices(session, txs):
    return [await session.get(Invoice, t.invoice_id) for t in txs]


async def test_installments_land_on_consecutive_invoices(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id)  # fecha 10, vence 20
    txs = await _buy(session, a, card, 30_000, date(2026, 11, 5), n=3)
    invs = await _invoices(session, txs)
    assert [(i.closing_on, i.due_on) for i in invs] == [
        (date(2026, 11, 10), date(2026, 11, 20)),
        (date(2026, 12, 10), date(2026, 12, 20)),
        (date(2027, 1, 10), date(2027, 1, 20)),
    ]
    assert [t.amount_cents for t in txs] == [10_000] * 3
    assert [(t.installment_number, t.installment_total) for t in txs] == [(1, 3), (2, 3), (3, 3)]
    assert len({t.installment_group_id for t in txs}) == 1 and txs[0].installment_group_id
    assert all(
        t.card_id == card.id and t.account_id is None and t.type == "expense"
        and t.occurred_on == date(2026, 11, 5)
        for t in txs
    )  # fmt: skip


async def test_installment_remainder_goes_to_first(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id)
    txs = await _buy(session, a, card, 1_000, date(2026, 11, 5), n=3)
    assert [t.amount_cents for t in txs] == [334, 333, 333]


async def test_installments_with_closing_day_31_clamp_each_month(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id, closing_day=31, due_day=10)
    txs = await _buy(session, a, card, 30_000, date(2026, 1, 31), n=3)
    invs = await _invoices(session, txs)
    assert [(i.closing_on, i.due_on) for i in invs] == [
        (date(2026, 1, 31), date(2026, 2, 10)),
        (date(2026, 2, 28), date(2026, 3, 10)),
        (date(2026, 3, 31), date(2026, 4, 10)),
    ]


async def test_single_purchase_has_no_installment_fields(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id)
    (tx,) = await _buy(session, a, card, 5_000, date(2026, 11, 5))
    assert tx.installment_group_id is None and tx.installment_number is None


async def test_invoice_has_mirror_bill_that_tracks_total(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id)
    t1 = (await _buy(session, a, card, 10_000, date(2026, 11, 1)))[0]
    t2 = (await _buy(session, a, card, 5_000, date(2026, 11, 9)))[0]
    assert t1.invoice_id == t2.invoice_id
    assert await invoice_total(session, t1.invoice_id) == 15_000
    bills = (await session.scalars(select(Bill))).all()
    assert len(bills) == 1
    bill = bills[0]
    assert (bill.kind, bill.amount_cents, bill.due_on, bill.status) == (
        "invoice", 15_000, date(2026, 11, 20), "open",
    )  # fmt: skip
    assert bill.space_id == card.space_id and bill.invoice_id == t1.invoice_id


async def test_invalid_installments_and_amounts(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id)
    for n in (0, 49):
        with pytest.raises(DomainError, match="invalid_installments"):
            await _buy(session, a, card, 1_000, date(2026, 11, 5), n=n)
    with pytest.raises(DomainError, match="amount_must_be_positive"):
        await _buy(session, a, card, 0, date(2026, 11, 5))
    with pytest.raises(DomainError, match="amount_too_small"):
        await _buy(session, a, card, 2, date(2026, 11, 5), n=3)
    assert (await session.scalars(select(Invoice))).all() == []  # nada pela metade


async def test_card_of_foreign_space_is_403(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    card = await make_card(session, a, a.default_space_id)
    with pytest.raises(HTTPException) as e:
        await _buy(session, b, card, 1_000, date(2026, 11, 5))
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        await use_card(session, b.id, card.id)
    assert e.value.status_code == 403


async def test_create_transaction_with_card_id_registers_purchase(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id)
    tx = await create_transaction(
        session, actor_id=a.id, space_id=a.default_space_id, type="expense", amount_cents=2_500,
        occurred_on=date(2026, 11, 5), card_id=card.id,
    )  # fmt: skip
    assert tx.invoice_id is not None and tx.card_id == card.id
    with pytest.raises(DomainError, match="invalid_card_purchase"):
        await create_transaction(
            session, actor_id=a.id, space_id=a.default_space_id, type="income",
            amount_cents=2_500, occurred_on=date(2026, 11, 5), card_id=card.id,
        )  # fmt: skip


async def test_shared_card_statement_aggregates_private_items(session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    card = await make_card(session, w, fam.id, name="Cartão da família")
    await _buy(session, w, card, 10_000, date(2026, 11, 2), space=fam.id, desc="mercado")
    (secret,) = await _buy(session, w, card, 4_000, date(2026, 11, 3), desc="presente")  # #pessoal
    inv_id = secret.invoice_id
    st_h = await invoice_statement(session, h.id, inv_id)
    assert [i.description for i in st_h.items] == ["mercado"]
    assert st_h.private_total_cents == 4_000
    assert st_h.total_cents == 14_000 == await invoice_total(session, inv_id)  # total fecha
    st_w = await invoice_statement(session, w.id, inv_id)
    assert sorted(i.description for i in st_w.items) == ["mercado", "presente"]
    assert st_w.private_total_cents == 0 and st_w.total_cents == 14_000


async def test_removed_member_loses_card_and_invoice_access(session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    card = await make_card(session, w, fam.id)
    (tx,) = await _buy(session, h, card, 3_000, date(2026, 11, 2), space=fam.id)
    await visible_invoice(session, h.id, tx.invoice_id)
    await remove_member(session, actor_id=w.id, space_id=fam.id, user_id=h.id)
    with pytest.raises(HTTPException) as e:
        await visible_invoice(session, h.id, tx.invoice_id)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        await _buy(session, h, card, 1_000, date(2026, 11, 3))
    assert e.value.status_code == 403
    st_w = await invoice_statement(session, w.id, tx.invoice_id)
    assert [i.amount_cents for i in st_w.items] == [3_000]  # o histórico (espaço família) fica


async def test_concurrent_purchases_same_card_month_create_one_invoice(session):
    import asyncio

    from app.core.db import SessionLocal

    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id)

    async def buy(i: int):
        async with SessionLocal() as s:
            return await _buy(s, a, card, 1_000 + i, date(2026, 11, 1))

    await asyncio.gather(*(buy(i) for i in range(5)))
    invoices = (await session.scalars(select(Invoice))).all()
    bills = (await session.scalars(select(Bill))).all()
    assert len(invoices) == 1 and len(bills) == 1
    assert await invoice_total(session, invoices[0].id) == sum(1_000 + i for i in range(5))
    await session.refresh(bills[0])
    assert bills[0].amount_cents == await invoice_total(session, invoices[0].id)


async def test_bill_status_matches_invoice_payments(session):
    from app.domain.cards.service import invoice_paid
    from app.domain.payments import pay_invoice
    from tests.factories import make_account

    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    card = await make_card(session, a, a.default_space_id)
    (buy,) = await _buy(session, a, card, 10_000, date(2026, 11, 1))
    for amount, status in ((4_000, "partial"), (6_000, "paid")):
        await pay_invoice(
            session, actor_id=a.id, invoice_id=buy.invoice_id, account_id=acc.id,
            paid_on=date(2026, 11, 20), amount_cents=amount,
        )  # fmt: skip
        bill = await session.scalar(select(Bill).where(Bill.invoice_id == buy.invoice_id))
        assert bill.status == status
    assert await invoice_paid(session, buy.invoice_id) == 10_000
