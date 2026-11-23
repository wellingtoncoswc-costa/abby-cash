from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, Session
from app.api.schemas import Cents
from app.domain.budgets.service import budget_overview, set_budget

router = APIRouter(tags=["budgets"])


class CategoryLimitIn(BaseModel):
    category_id: UUID
    limit_cents: Cents


class BudgetIn(BaseModel):
    limit_cents: Cents
    categories: list[CategoryLimitIn] = []


def _month(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_month") from None


@router.put("/spaces/{space_id}/budgets/{month}")
async def put_budget(
    space_id: UUID, month: str, body: BudgetIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    m = _month(month)
    await set_budget(
        session, actor_id=user.id, space_id=space_id, month=m, limit_cents=body.limit_cents,
        categories={c.category_id: c.limit_cents for c in body.categories},
    )  # fmt: skip
    return await budget_overview(session, viewer_id=user.id, space_id=space_id, month=m)


@router.get("/spaces/{space_id}/budgets/{month}")
async def get_budget(
    space_id: UUID, month: str, user: CurrentUser, session: Session
) -> dict[str, Any]:
    return await budget_overview(session, viewer_id=user.id, space_id=space_id, month=_month(month))
