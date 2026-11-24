from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.audit import audit
from app.domain.bills.models import Bill
from app.domain.bills.recurrence import Recurrence
from app.domain.errors import DomainError
from app.domain.spaces.access import is_member, require_member
from app.domain.transactions.rules import check_common


async def create_bill(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, description: str, amount_cents: int,
    due_on: date, category_id: UUID | None = None, responsible_user_id: UUID | None = None,
    recurrence: Recurrence | None = None,
) -> Bill:  # fmt: skip
    """Conta a pagar avulsa ou recorrente. A próxima ocorrência é gerada pelo job do M5."""
    await check_common(
        session, actor_id=actor_id, space_id=space_id, type="expense", amount_cents=amount_cents,
        category_id=category_id, occurred_on=due_on,
    )  # fmt: skip
    resp = responsible_user_id
    if resp is not None and not await is_member(session, resp, space_id):
        raise DomainError("invalid_responsible")
    bill = Bill(
        space_id=space_id, kind="manual", description=description, amount_cents=amount_cents,
        due_on=due_on, category_id=category_id, responsible_user_id=responsible_user_id,
        recurrence_rule=recurrence.to_json() if recurrence else None,
    )  # fmt: skip
    session.add(bill)
    await session.flush()
    audit(
        session,
        actor_id,
        "bill.create",
        "bill",
        bill.id,
        {"space_id": str(space_id), "amount_cents": amount_cents},
    )
    await session.commit()
    return bill


async def list_bills(
    session: AsyncSession, *, viewer_id: UUID, space_id: UUID, status: str | None = None,
    start: date | None = None, end: date | None = None,
) -> list[Bill]:  # fmt: skip
    await require_member(session, viewer_id, space_id)
    q = select(Bill).where(Bill.space_id == space_id)
    if status is not None:
        q = q.where(Bill.status == status)
    if start is not None:
        q = q.where(Bill.due_on >= start)
    if end is not None:
        q = q.where(Bill.due_on <= end)
    return list(await session.scalars(q.order_by(Bill.due_on, Bill.created_at)))
