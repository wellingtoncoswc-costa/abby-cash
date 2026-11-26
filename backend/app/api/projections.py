from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import CurrentUser, Session
from app.core.dates import local_today
from app.domain.projections.service import projections

router = APIRouter(tags=["projections"])


class ProjMonthOut(BaseModel):
    month: date
    income_fixed_cents: int
    income_estimated_cents: int
    expense_fixed_cents: int
    expense_loans_cents: int
    expense_cards_cents: int
    expense_bills_cents: int
    expense_estimated_cents: int
    net_committed_cents: int
    net_cents: int
    projected_balance_committed_cents: int
    projected_balance_cents: int
    commitment_bp: int | None


class ProjHistoryOut(BaseModel):
    month: str
    income_cents: int
    expense_cents: int
    net_cents: int
    balance_cents: int


class ProjLoanEndOut(BaseModel):
    loan_id: UUID
    name: str
    kind: str
    last_due_on: date
    installment_cents: int
    remaining_count: int


class ProjAveragesOut(BaseModel):
    estimated_income_cents: int
    estimated_expense_cents: int
    history_income_cents: int
    history_expense_cents: int


class ProjectionsOut(BaseModel):
    current_balance_cents: int
    months: list[ProjMonthOut]
    history: list[ProjHistoryOut]
    loans_ending: list[ProjLoanEndOut]
    averages: ProjAveragesOut


@router.get("/spaces/{space_id}/projections", response_model=ProjectionsOut)
async def get_projections(
    space_id: UUID, user: CurrentUser, session: Session,
    months: Annotated[int, Query(ge=6, le=12)] = 12,
) -> dict[str, Any]:  # fmt: skip
    return await projections(
        session, viewer_id=user.id, space_id=space_id, today=local_today(user.tz), months=months
    )
