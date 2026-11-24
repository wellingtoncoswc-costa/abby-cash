from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bills.models import Bill
from app.domain.transactions.models import Transaction


async def bill_paid_cents(session: AsyncSession, bill_id: UUID) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.bill_id == bill_id
        )
    )
    return int(total or 0)


async def invoice_paid(session: AsyncSession, invoice_id: UUID) -> int:
    paid = await session.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.invoice_id == invoice_id, Transaction.type == "transfer"
        )
    )
    return int(paid or 0)


async def refresh_status(session: AsyncSession, bill: Bill) -> None:
    if bill.settled_historical_at is not None:  # baixa histórica: paga sem pagamento
        bill.status = "paid"
        return
    # conta espelho de fatura usa a mesma fonte de invoice_paid (status e pago não divergem)
    paid = (
        await invoice_paid(session, bill.invoice_id)
        if bill.invoice_id
        else await bill_paid_cents(session, bill.id)
    )
    bill.status = "open" if paid <= 0 else "paid" if paid >= bill.amount_cents else "partial"
