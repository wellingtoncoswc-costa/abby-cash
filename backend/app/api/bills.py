from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Session
from app.api.schemas import Cents
from app.core.dates import local_today
from app.core.serialize import row
from app.domain.bills.recurrence import Recurrence
from app.domain.bills.service import create_bill, list_bills
from app.domain.payments import pay_bill, pay_invoice

router = APIRouter(tags=["bills"])


class RecurrenceIn(BaseModel):
    kind: Literal["monthly", "yearly", "every_n_months"]
    day: Annotated[int, Field(strict=True, ge=1, le=31)]
    month: Annotated[int, Field(strict=True, ge=1, le=12)] | None = None
    n: Annotated[int, Field(strict=True, ge=1)] = 1


class BillIn(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    amount_cents: Cents
    due_on: date
    category_id: UUID | None = None
    responsible_user_id: UUID | None = None
    recurrence: RecurrenceIn | None = None


class PayBillIn(BaseModel):
    account_id: UUID  # obrigatório: todo pagamento tem conta de origem (pode ser a carteira)
    amount_cents: Cents | None = None  # padrão: o que falta
    paid_on: date | None = None


class PayInvoiceIn(BaseModel):
    account_id: UUID
    amount_cents: Cents
    paid_on: date | None = None


@router.post("/spaces/{space_id}/bills", status_code=201)
async def create(
    space_id: UUID, body: BillIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    bill = await create_bill(
        session, actor_id=user.id, space_id=space_id, description=body.description,
        amount_cents=body.amount_cents, due_on=body.due_on, category_id=body.category_id,
        responsible_user_id=body.responsible_user_id,
        recurrence=Recurrence(**body.recurrence.model_dump()) if body.recurrence else None,
    )  # fmt: skip
    return row(bill)


@router.get("/spaces/{space_id}/bills")
async def list_(
    space_id: UUID, user: CurrentUser, session: Session, status: str | None = None,
    start: date | None = None, end: date | None = None,
) -> list[dict[str, Any]]:  # fmt: skip
    bills = await list_bills(
        session, viewer_id=user.id, space_id=space_id, status=status, start=start, end=end
    )
    return [row(b) for b in bills]


@router.post("/bills/{bill_id}/payments", status_code=201)
async def pay(
    bill_id: UUID, body: PayBillIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    tx = await pay_bill(
        session, actor_id=user.id, bill_id=bill_id, account_id=body.account_id,
        paid_on=body.paid_on or local_today(user.tz), amount_cents=body.amount_cents,
    )  # fmt: skip
    return row(tx)


@router.post("/invoices/{invoice_id}/payments", status_code=201)
async def pay_inv(
    invoice_id: UUID, body: PayInvoiceIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    tx = await pay_invoice(
        session, actor_id=user.id, invoice_id=invoice_id, account_id=body.account_id,
        paid_on=body.paid_on or local_today(user.tz), amount_cents=body.amount_cents,
    )  # fmt: skip
    return row(tx)
