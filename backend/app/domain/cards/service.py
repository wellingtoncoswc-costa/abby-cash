from datetime import date
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import add_months
from app.domain.accounts.access import use_account
from app.domain.accounts.statement import Statement, build_statement
from app.domain.audit import audit
from app.domain.bills.models import Bill
from app.domain.bills.status import invoice_paid, refresh_status
from app.domain.cards.billing import (
    InvoiceDates,
    invoice_dates_for_month,
    invoice_dates_for_purchase,
    split_installments,
)
from app.domain.cards.models import CreditCard, Invoice
from app.domain.errors import DomainError
from app.domain.spaces.access import is_member, require_member
from app.domain.transactions.models import Transaction
from app.domain.transactions.rules import check_common

MAX_INSTALLMENTS = 48


async def create_card(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, name: str, closing_day: int,
    due_day: int, limit_cents: int | None = None, payment_account_id: UUID | None = None,
) -> CreditCard:  # fmt: skip
    await require_member(session, actor_id, space_id)
    if not (1 <= closing_day <= 31 and 1 <= due_day <= 31):
        raise DomainError("invalid_day")
    if limit_cents is not None and limit_cents <= 0:
        raise DomainError("amount_must_be_positive")
    if payment_account_id is not None:
        await use_account(session, actor_id, payment_account_id)
    card = CreditCard(
        space_id=space_id, name=name, closing_day=closing_day, due_day=due_day,
        limit_cents=limit_cents, payment_account_id=payment_account_id,
    )  # fmt: skip
    session.add(card)
    await session.flush()
    audit(session, actor_id, "card.create", "card", card.id, {"space_id": str(space_id)})
    await session.commit()
    return card


async def use_card(session: AsyncSession, actor_id: UUID, card_id: UUID) -> CreditCard:
    """Cartão que o autor pode usar: membro do espaço dono do cartão (spec 14.1), senão 403."""
    card = await session.get(CreditCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="card_not_found")
    if not await is_member(session, actor_id, card.space_id):
        raise HTTPException(status_code=403, detail="card_forbidden")
    return card


async def visible_card(session: AsyncSession, viewer_id: UUID, card_id: UUID) -> CreditCard:
    card = await session.get(CreditCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="not_found")
    await require_member(session, viewer_id, card.space_id)
    return card


async def visible_invoice(
    session: AsyncSession, viewer_id: UUID, invoice_id: UUID
) -> tuple[Invoice, CreditCard]:
    inv = await session.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="not_found")
    card = await visible_card(session, viewer_id, inv.card_id)
    return inv, card


async def invoice_total(session: AsyncSession, invoice_id: UUID) -> int:
    """Soma das compras da fatura (inclui as de espaços privados para quem vê)."""
    total = await session.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.invoice_id == invoice_id, Transaction.type == "expense"
        )
    )
    return int(total or 0)


async def invoice_remaining(session: AsyncSession, invoice_id: UUID) -> int:
    return await invoice_total(session, invoice_id) - await invoice_paid(session, invoice_id)


async def invoice_summary(session: AsyncSession, invoice: Invoice) -> dict[str, Any]:
    total = await invoice_total(session, invoice.id)
    paid = await invoice_paid(session, invoice.id)
    bill = await session.scalar(select(Bill).where(Bill.invoice_id == invoice.id))
    return {
        "total_cents": total, "paid_cents": paid, "remaining_cents": total - paid,
        "status": bill.status if bill else "open",
    }  # fmt: skip


async def get_or_create_invoice(
    session: AsyncSession, card: CreditCard, dates: InvoiceDates
) -> Invoice:
    # corrida (mesma fatura em compras simultâneas): INSERT ... ON CONFLICT DO NOTHING e relê;
    # a perdedora espera o commit da vencedora, então vê a fatura e a conta espelho dela
    await session.execute(
        pg_insert(Invoice)
        .values(card_id=card.id, closing_on=dates.closing, due_on=dates.due)
        .on_conflict_do_nothing(constraint="uq_invoices_card_closing")
    )
    inv = await session.scalar(
        select(Invoice)
        .where(Invoice.card_id == card.id, Invoice.closing_on == dates.closing)
        .execution_options(populate_existing=True)
    )
    assert inv is not None
    await session.execute(
        pg_insert(Bill)
        .values(
            space_id=card.space_id, kind="invoice", amount_cents=0, due_on=dates.due,
            description=f"Fatura {card.name} {dates.closing:%m/%Y}", invoice_id=inv.id,
        )
        .on_conflict_do_nothing(index_elements=[Bill.invoice_id])
    )  # fmt: skip
    return inv


async def sync_invoice_bill(session: AsyncSession, invoice: Invoice) -> None:
    """Mantém a conta espelho = total da fatura (chamar após gravar/alterar compras)."""
    bill = await session.scalar(
        select(Bill)
        .where(Bill.invoice_id == invoice.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )  # trava antes de somar: compras simultâneas não sobrescrevem o total com valor velho
    assert bill is not None
    bill.amount_cents = await invoice_total(session, invoice.id)
    bill.due_on = invoice.due_on
    await refresh_status(session, bill)


async def register_card_purchase(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, card_id: UUID, amount_cents: int,
    occurred_on: date, installments: int = 1, description: str = "", merchant: str | None = None,
    category_id: UUID | None = None, origin: str = "web", source_message_id: str | None = None,
    attachment_id: UUID | None = None,
) -> list[Transaction]:  # fmt: skip
    """`occurred_on` é o dia local do usuário. Cada parcela vai para a sua fatura."""
    await check_common(
        session, actor_id=actor_id, space_id=space_id, type="expense", amount_cents=amount_cents,
        category_id=category_id, occurred_on=occurred_on,
    )  # fmt: skip
    if not 1 <= installments <= MAX_INSTALLMENTS:
        raise DomainError("invalid_installments")
    card = await use_card(session, actor_id, card_id)
    parts = split_installments(amount_cents, installments)
    first = invoice_dates_for_purchase(card.closing_day, card.due_day, occurred_on)
    group = uuid4() if installments > 1 else None
    txs: list[Transaction] = []
    invoices: dict[UUID, Invoice] = {}
    for i, part in enumerate(parts):
        month = add_months(first.closing.replace(day=1), i)
        dates = invoice_dates_for_month(card.closing_day, card.due_day, month.year, month.month)
        inv = await get_or_create_invoice(session, card, dates)
        invoices[inv.id] = inv
        tx = Transaction(
            space_id=space_id, type="expense", amount_cents=part, occurred_on=occurred_on,
            description=description, merchant=merchant, category_id=category_id,
            card_id=card.id, invoice_id=inv.id, installment_group_id=group,
            installment_number=i + 1 if group else None,
            installment_total=installments if group else None,
            created_by=actor_id, origin=origin, source_message_id=source_message_id,
            attachment_id=attachment_id,
        )  # fmt: skip
        session.add(tx)
        txs.append(tx)
    await session.flush()
    for inv in invoices.values():
        await sync_invoice_bill(session, inv)
    audit(
        session,
        actor_id,
        "card.purchase",
        "card",
        card.id,
        {"space_id": str(space_id), "amount_cents": amount_cents, "installments": installments},
    )
    await session.commit()
    return txs


async def invoice_statement(session: AsyncSession, viewer_id: UUID, invoice_id: UUID) -> Statement:
    """Compras da fatura; as de espaços de que o visualizador não é membro viram agregado."""
    inv, _ = await visible_invoice(session, viewer_id, invoice_id)
    txs = await session.scalars(
        select(Transaction)
        .where(Transaction.invoice_id == inv.id, Transaction.type == "expense")
        .order_by(Transaction.occurred_on, Transaction.created_at)
    )
    return await build_statement(session, viewer_id, [(t, t.amount_cents) for t in txs])
