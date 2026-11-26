from datetime import date

from sqlalchemy import select

from app.domain.bills.models import Bill
from app.domain.cards.panel import card_panel
from app.domain.cards.service import (
    invoice_statement,
    invoice_summary,
    invoice_total,
    register_card_credit,
    register_card_purchase,
)
from app.domain.transactions.service import delete_transaction
from tests.factories import make_card, make_user

D = date(2026, 11, 5)


async def _setup(session, limit=None):
    a = await make_user(session, "a@x.com")
    card = await make_card(
        session, a, a.default_space_id, closing_day=10, due_day=20, limit_cents=limit
    )
    return a, card


async def test_credit_reduces_the_invoice_and_can_make_it_negative(session):
    a, card = await _setup(session)
    sp = a.default_space_id
    [buy] = await register_card_purchase(
        session, actor_id=a.id, space_id=sp, card_id=card.id, amount_cents=10_000, occurred_on=D
    )
    credit = await register_card_credit(
        session, actor_id=a.id, card_id=card.id, amount_cents=4_000, occurred_on=D,
        description="Estorno",
    )  # fmt: skip
    assert credit.invoice_id == buy.invoice_id and credit.type == "income"
    assert await invoice_total(session, buy.invoice_id) == 6_000
    over = await register_card_credit(
        session, actor_id=a.id, card_id=card.id, amount_cents=9_000, occurred_on=D
    )
    assert await invoice_total(session, buy.invoice_id) == -3_000  # crédito a favor
    bill = await session.scalar(select(Bill).where(Bill.invoice_id == buy.invoice_id))
    assert bill.amount_cents == 0  # a conta a pagar nunca fica negativa
    st = await invoice_statement(session, a.id, buy.invoice_id)
    assert sorted(i.amount_cents for i in st.items) == [-9_000, -4_000, 10_000]
    await delete_transaction(session, actor_id=a.id, tx_id=over.id)  # apagar o crédito reajusta
    assert await invoice_total(session, buy.invoice_id) == 6_000
    await session.refresh(bill)
    assert bill.amount_cents == 6_000


async def test_panel_used_ignores_credit_invoices(session):
    a, card = await _setup(session, limit=100_000)
    await register_card_credit(
        session, actor_id=a.id, card_id=card.id, amount_cents=5_000, occurred_on=D
    )
    p = await card_panel(session, a.id, card.id, today=D)
    assert p["invoice"]["total_cents"] == -5_000 and p["used_cents"] == 0
    assert p["available_cents"] == 100_000
    inv = p["invoice"]
    from app.domain.cards.models import Invoice

    summary = await invoice_summary(session, await session.get(Invoice, inv["id"]))
    assert summary["remaining_cents"] <= 0


async def test_card_credit_is_not_income_in_reports(session):
    from app.domain.reports.service import _totals
    from app.domain.transactions.service import Filters

    a, card = await _setup(session)
    await register_card_credit(
        session, actor_id=a.id, card_id=card.id, amount_cents=4_000, occurred_on=D
    )
    t = await _totals(session, a.default_space_id, Filters(), date(2026, 11, 1), date(2026, 12, 31))
    assert t["income_cents"] == 0 and t["tx_count"] == 0
