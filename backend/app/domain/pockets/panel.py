from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import add_months
from app.domain.goals.models import Goal, GoalPocket
from app.domain.pockets.models import PocketMovement
from app.domain.pockets.service import visible_pocket
from app.domain.spaces.models import SpaceMember


async def pocket_panel(
    session: AsyncSession, viewer_id: UUID, pocket_id: UUID, *, today: date
) -> dict[str, Any]:  # fmt: skip
    """Rendimento dos últimos 6 meses (meses sem rendimento vêm com 0) e metas ligadas
    (só de espaços do visualizador)."""
    pocket = await visible_pocket(session, viewer_id, pocket_id)
    this = today.replace(day=1)
    months = [add_months(this, -n) for n in range(5, -1, -1)]
    month = func.date_trunc("month", PocketMovement.ref_date)
    rows = await session.execute(
        select(month, func.sum(PocketMovement.amount_cents)).where(
            PocketMovement.pocket_id == pocket.id,
            PocketMovement.kind == "accrual",
            PocketMovement.ref_date >= months[0],
        ).group_by(month)
    )  # fmt: skip
    got = {m.date(): int(v) for m, v in rows}
    mine = select(SpaceMember.space_id).where(SpaceMember.user_id == viewer_id)
    goals = await session.scalars(
        select(Goal)
        .join(GoalPocket, GoalPocket.goal_id == Goal.id)
        .where(GoalPocket.pocket_id == pocket.id, Goal.space_id.in_(mine))
        .order_by(Goal.name)
    )
    return {
        "yield_by_month": [{"month": m, "yield_cents": got.get(m, 0)} for m in months],
        "goals": [{"id": g.id, "name": g.name} for g in goals],
    }
