from datetime import date
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.access import use_account
from app.domain.bills.models import Bill
from app.domain.bills.status import bill_paid_cents, refresh_status
from app.domain.cards.service import invoice_remaining, visible_invoice
from app.domain.errors import DomainError
from app.domain.spaces.access import require_member
from app.domain.transactions.models import Transaction
from app.domain.transactions.rules import check_common


async def pay_bill(
    session: AsyncSession, *, actor_id: UUID, bill_id: UUID, account_id: UUID | None,
    paid_on: date, amount_cents: int | None = None,
) -> Transaction:  # fmt: skip
    """Quita (ou paga parte de) uma conta a pagar: despesa na conta de origem, que é obrigatória."""
    if account_id is None:
        raise DomainError("source_account_required")
    bill = await session.get(Bill, bill_id, with_for_update=True, populate_existing=True)
    if bill is None:
        raise HTTPException(status_code=404, detail="not_found")
    await require_member(session, actor_id, bill.space_id)
    if bill.kind != "manual":
        raise DomainError("use_pay_invoice")
    await use_account(session, actor_id, account_id)
    remaining = bill.amount_cents - await bill_paid_cents(session, bill.id)
    amount = remaining if amount_cents is None else amount_cents
    if amount <= 0 or amount > remaining:
        raise DomainError("invalid_payment_amount")
    await check_common(
        session, actor_id=actor_id, space_id=bill.space_id, type="expense", amount_cents=amount,
        category_id=bill.category_id, occurred_on=paid_on,
    )  # fmt: skip
    tx = Transaction(
        space_id=bill.space_id, type="expense", amount_cents=amount, occurred_on=paid_on,
        description=bill.description, category_id=bill.category_id, account_id=account_id,
        bill_id=bill.id, created_by=actor_id, origin="web",
    )  # fmt: skip
    session.add(tx)
    await session.flush()
    await refresh_status(session, bill)
    await session.commit()
    return tx


async def pay_invoice(
    session: AsyncSession, *, actor_id: UUID, invoice_id: UUID, account_id: UUID | None,
    paid_on: date, amount_cents: int,
) -> Transaction:  # fmt: skip
    """Transferência conta -> cartão (não é despesa). Parcial permitido; o resto fica em aberto."""
    if account_id is None:
        raise DomainError("source_account_required")
    inv, card = await visible_invoice(session, actor_id, invoice_id)  # 404 se não for membro
    acc = await use_account(session, actor_id, account_id)
    bill = await session.scalar(
        select(Bill).where(Bill.invoice_id == inv.id).with_for_update()
    )  # trava contra pagamento duplo
    assert bill is not None
    remaining = await invoice_remaining(session, inv.id)
    if amount_cents <= 0 or amount_cents > remaining:
        raise DomainError("invalid_payment_amount")
    await check_common(
        session, actor_id=actor_id, space_id=acc.space_id, type="transfer",
        amount_cents=amount_cents, category_id=None, occurred_on=paid_on,
    )  # fmt: skip
    tx = Transaction(
        space_id=acc.space_id,  # espaço da conta de origem: não expõe a conta a outros membros
        type="transfer", amount_cents=amount_cents, occurred_on=paid_on,
        description=f"Pagamento da fatura {card.name}", account_id=acc.id, card_id=card.id,
        invoice_id=inv.id, bill_id=bill.id, created_by=actor_id, origin="web",
    )  # fmt: skip
    session.add(tx)
    await session.flush()
    await refresh_status(session, bill)
    await session.commit()
    return tx
