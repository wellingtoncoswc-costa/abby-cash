from dataclasses import dataclass
from datetime import date
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dates import local_today
from app.domain.accounts.access import use_account
from app.domain.audit import audit
from app.domain.errors import DomainError
from app.domain.goals.models import Goal
from app.domain.spaces.access import require_member
from app.domain.transactions.models import Transaction


@dataclass(frozen=True)
class GoalProgress:
    saved: int
    target: int
    monthly_needed: int | None  # None: meta sem prazo
    behind: bool


async def create_goal(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, name: str, target_cents: int,
    created_on: date, deadline: date | None = None, account_id: UUID | None = None,
) -> Goal:  # fmt: skip
    await require_member(session, actor_id, space_id)
    if target_cents <= 0:
        raise DomainError("amount_must_be_positive")
    if account_id is not None:
        await use_account(session, actor_id, account_id)
    goal = Goal(
        space_id=space_id, name=name, target_cents=target_cents, deadline=deadline,
        account_id=account_id, created_on=created_on,
    )  # fmt: skip
    session.add(goal)
    await session.flush()
    audit(
        session,
        actor_id,
        "goal.create",
        "goal",
        goal.id,
        {"space_id": str(space_id), "target_cents": target_cents},
    )
    await session.commit()
    return goal


async def visible_goal(session: AsyncSession, viewer_id: UUID, goal_id: UUID) -> Goal:
    goal = await session.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="not_found")
    await require_member(session, viewer_id, goal.space_id)
    return goal


async def goal_saved(session: AsyncSession, goal_id: UUID) -> int:
    """Aportes (account_id preenchido) menos retiradas (account_id nulo)."""
    delta = case(
        (Transaction.account_id.is_not(None), Transaction.amount_cents),
        else_=-Transaction.amount_cents,
    )
    total = await session.scalar(
        select(func.coalesce(func.sum(delta), 0)).where(Transaction.goal_id == goal_id)
    )
    return int(total or 0)


async def contribute(
    session: AsyncSession, *, actor_id: UUID, goal_id: UUID, from_account_id: UUID,
    amount_cents: int, on: date,
) -> Transaction:  # fmt: skip
    goal = await visible_goal(session, actor_id, goal_id)
    if amount_cents <= 0:
        raise DomainError("amount_must_be_positive")
    await use_account(session, actor_id, from_account_id)
    tx = Transaction(
        space_id=goal.space_id, type="transfer", amount_cents=amount_cents, occurred_on=on,
        description=f"Aporte: {goal.name}", account_id=from_account_id, goal_id=goal.id,
        created_by=actor_id, origin="web",
    )  # fmt: skip
    session.add(tx)
    await session.flush()
    audit(
        session,
        actor_id,
        "goal.contribute",
        "goal",
        goal.id,
        {"transaction_id": str(tx.id), "amount_cents": amount_cents},
    )
    await session.commit()
    return tx


async def withdraw(
    session: AsyncSession, *, actor_id: UUID, goal_id: UUID, to_account_id: UUID,
    amount_cents: int, on: date,
) -> Transaction:  # fmt: skip
    """Transferência inversa: da meta para a conta de destino."""
    goal = await visible_goal(session, actor_id, goal_id)
    if amount_cents <= 0:
        raise DomainError("amount_must_be_positive")
    await use_account(session, actor_id, to_account_id)
    await session.refresh(goal, with_for_update=True)  # serializa retiradas da mesma meta
    if amount_cents > await goal_saved(session, goal.id):
        raise DomainError("insufficient_saved")
    tx = Transaction(
        space_id=goal.space_id, type="transfer", amount_cents=amount_cents, occurred_on=on,
        description=f"Retirada: {goal.name}", account_id=None, counter_account_id=to_account_id,
        goal_id=goal.id, created_by=actor_id, origin="web",
    )  # fmt: skip
    session.add(tx)
    await session.flush()
    audit(
        session,
        actor_id,
        "goal.withdraw",
        "goal",
        goal.id,
        {"transaction_id": str(tx.id), "amount_cents": amount_cents},
    )
    await session.commit()
    return tx


async def goal_progress(
    session: AsyncSession, goal_id: UUID, *, today: date | None = None
) -> GoalProgress:
    """`monthly_needed` = falta / meses até o prazo (mín. 1, arredondado p/ cima).
    `behind` = guardado < esperado por um ritmo linear de `created_on` até o prazo."""
    goal = await session.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="not_found")
    today = today or local_today(get_settings().DEFAULT_TZ)
    saved = await goal_saved(session, goal.id)
    if goal.deadline is None:
        return GoalProgress(saved, goal.target_cents, None, False)
    remaining = max(0, goal.target_cents - saved)
    months_left = max(1, (goal.deadline.year - today.year) * 12 + goal.deadline.month - today.month)
    total_days = (goal.deadline - goal.created_on).days
    if total_days <= 0:
        expected = goal.target_cents if today >= goal.deadline else 0
    else:
        elapsed = min(max((today - goal.created_on).days, 0), total_days)
        expected = goal.target_cents * elapsed // total_days
    return GoalProgress(saved, goal.target_cents, -(-remaining // months_left), saved < expected)
