from dataclasses import asdict
from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Session
from app.api.schemas import BillOut, Cents, InstallmentOut, LoanOut
from app.core.serialize import row
from app.domain.loans.models import Loan
from app.domain.loans.service import (
    cancel_loan,
    create_loan,
    list_installments,
    list_loans,
    loan_progress,
    materialize_installment,
    settle_installment,
    unsettle_installment,
    update_loan,
    visible_loan,
)

router = APIRouter(tags=["loans"])


class LoanIn(BaseModel):
    kind: Literal["financing", "consortium"]
    name: str = Field(min_length=1, max_length=100)
    installment_cents: Cents
    installments_total: Annotated[int, Field(strict=True, ge=1, le=480)]
    first_due_on: date
    category_id: UUID | None = None
    account_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=500)
    paid_installments: Annotated[int, Field(strict=True, ge=0, le=480)] = 0


class LoanPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    installment_cents: Cents | None = None


async def _out(session: Any, loan: Loan) -> dict[str, Any]:
    p = await loan_progress(session, loan)
    return row(loan) | {
        "paid_count": p.paid_count, "remaining_count": p.remaining_count,
        "remaining_cents": p.remaining_cents, "next_due_on": p.next_due_on,
        "last_due_on": p.last_due_on, "progress_pct": p.progress_pct,
    }  # fmt: skip


@router.post("/spaces/{space_id}/loans", status_code=201, response_model=LoanOut)
async def create(
    space_id: UUID, body: LoanIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    loan = await create_loan(session, actor_id=user.id, space_id=space_id, **body.model_dump())
    return await _out(session, loan)


@router.get("/spaces/{space_id}/loans", response_model=list[LoanOut])
async def list_(space_id: UUID, user: CurrentUser, session: Session) -> list[dict[str, Any]]:
    loans = await list_loans(session, viewer_id=user.id, space_id=space_id)
    return [await _out(session, ln) for ln in loans]


@router.get("/loans/{loan_id}", response_model=LoanOut)
async def get(loan_id: UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    return await _out(session, await visible_loan(session, user.id, loan_id))


@router.patch("/loans/{loan_id}", response_model=LoanOut)
async def patch(
    loan_id: UUID, body: LoanPatch, user: CurrentUser, session: Session
) -> dict[str, Any]:
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    return await _out(
        session, await update_loan(session, actor_id=user.id, loan_id=loan_id, fields=fields)
    )


@router.delete("/loans/{loan_id}", status_code=204)
async def delete(loan_id: UUID, user: CurrentUser, session: Session) -> None:
    await cancel_loan(session, actor_id=user.id, loan_id=loan_id)


@router.get("/loans/{loan_id}/installments", response_model=list[InstallmentOut])
async def installments(loan_id: UUID, user: CurrentUser, session: Session) -> list[Any]:
    loan = await visible_loan(session, user.id, loan_id)
    return [asdict(i) for i in await list_installments(session, loan)]


@router.post("/loans/{loan_id}/installments/{number}/settle", response_model=InstallmentOut)
async def settle(loan_id: UUID, number: int, user: CurrentUser, session: Session) -> Any:
    i = await settle_installment(session, actor_id=user.id, loan_id=loan_id, number=number)
    return asdict(i)


@router.delete("/loans/{loan_id}/installments/{number}/settle", response_model=InstallmentOut)
async def unsettle(loan_id: UUID, number: int, user: CurrentUser, session: Session) -> Any:
    i = await unsettle_installment(session, actor_id=user.id, loan_id=loan_id, number=number)
    return asdict(i)


@router.post("/loans/{loan_id}/installments/{number}/materialize", response_model=BillOut)
async def materialize(loan_id: UUID, number: int, user: CurrentUser, session: Session) -> Any:
    b = await materialize_installment(session, actor_id=user.id, loan_id=loan_id, number=number)
    return row(b)
