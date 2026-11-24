from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Session
from app.api.schemas import Cents, GoalOut, GoalProgressOut, TransactionOut
from app.core.dates import local_today
from app.core.serialize import row
from app.domain.goals.models import Goal
from app.domain.goals.service import (
    GoalProgress,
    contribute,
    create_goal,
    delete_goal,
    goal_progress,
    update_goal,
    visible_goal,
    withdraw,
)
from app.domain.spaces.access import require_member

MIN_DATE, MAX_DATE = date(2000, 1, 1), date(2100, 12, 31)  # igual a check_common

router = APIRouter(tags=["goals"])


class GoalIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    target_cents: Cents
    deadline: date | None = None
    account_id: UUID | None = None


class ContributionIn(BaseModel):
    from_account_id: UUID
    amount_cents: Cents
    occurred_on: date | None = Field(default=None, ge=MIN_DATE, le=MAX_DATE)


class WithdrawalIn(BaseModel):
    to_account_id: UUID
    amount_cents: Cents
    occurred_on: date | None = Field(default=None, ge=MIN_DATE, le=MAX_DATE)


def _progress(p: GoalProgress) -> dict[str, Any]:
    return {
        "saved_cents": p.saved, "target_cents": p.target,
        "monthly_needed_cents": p.monthly_needed, "behind": p.behind,
    }  # fmt: skip


@router.post("/spaces/{space_id}/goals", status_code=201, response_model=GoalOut)
async def create(
    space_id: UUID, body: GoalIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    goal = await create_goal(
        session, actor_id=user.id, space_id=space_id, name=body.name,
        target_cents=body.target_cents, deadline=body.deadline, account_id=body.account_id,
        created_on=local_today(user.tz),
    )  # fmt: skip
    return row(goal)


@router.get("/spaces/{space_id}/goals", response_model=list[GoalProgressOut])
async def list_goals(space_id: UUID, user: CurrentUser, session: Session) -> list[dict[str, Any]]:
    await require_member(session, user.id, space_id)
    goals = await session.scalars(
        select(Goal).where(Goal.space_id == space_id).order_by(Goal.created_at)
    )
    # ponytail: progresso por meta = 1 query cada (N+1); ok p/ poucas metas, agregar se crescer
    return [row(g) | _progress(await goal_progress(session, g.id, today=local_today(user.tz)))
            for g in goals]  # fmt: skip


@router.get("/goals/{goal_id}", response_model=GoalProgressOut)
async def get_goal(goal_id: UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    goal = await visible_goal(session, user.id, goal_id)
    return row(goal) | _progress(await goal_progress(session, goal.id, today=local_today(user.tz)))


@router.post("/goals/{goal_id}/contributions", status_code=201, response_model=TransactionOut)
async def add_contribution(
    goal_id: UUID, body: ContributionIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    tx = await contribute(
        session, actor_id=user.id, goal_id=goal_id, from_account_id=body.from_account_id,
        amount_cents=body.amount_cents, on=body.occurred_on or local_today(user.tz),
    )  # fmt: skip
    return row(tx)


@router.post("/goals/{goal_id}/withdrawals", status_code=201, response_model=TransactionOut)
async def add_withdrawal(
    goal_id: UUID, body: WithdrawalIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    tx = await withdraw(
        session, actor_id=user.id, goal_id=goal_id, to_account_id=body.to_account_id,
        amount_cents=body.amount_cents, on=body.occurred_on or local_today(user.tz),
    )  # fmt: skip
    return row(tx)


class GoalPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    target_cents: Cents | None = None
    deadline: date | None = None  # null remove o prazo


@router.patch("/goals/{goal_id}", response_model=GoalProgressOut)
async def patch(
    goal_id: UUID, body: GoalPatch, user: CurrentUser, session: Session
) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    for k in ("name", "target_cents"):
        if k in fields and fields[k] is None:
            del fields[k]
    goal = await update_goal(session, actor_id=user.id, goal_id=goal_id, fields=fields)
    return row(goal) | _progress(await goal_progress(session, goal.id, today=local_today(user.tz)))


@router.delete("/goals/{goal_id}", status_code=204)
async def delete(goal_id: UUID, user: CurrentUser, session: Session) -> None:
    await delete_goal(session, actor_id=user.id, goal_id=goal_id)
