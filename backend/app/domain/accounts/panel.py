from calendar import monthrange
from collections import defaultdict
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.access import visible_account
from app.domain.accounts.statement import account_statement
from app.domain.goals.models import Goal, GoalAccount, GoalPocket
from app.domain.pockets.models import Pocket
from app.domain.pockets.service import pocket_stats
from app.domain.spaces.models import SpaceMember


async def account_panel(
    session: AsyncSession, viewer_id: UUID, account_id: UUID, *, month: date, today: date
) -> dict[str, Any]:  # fmt: skip
    """Mês `month` (qualquer dia): entradas, saídas, transferências, categorias, últimas
    movimentações, caixinhas e metas ligadas. Itens de espaços alheios só em `private_total_cents`.
    """
    acc = await visible_account(session, viewer_id, account_id)
    start = month.replace(day=1)
    end = month.replace(day=monthrange(month.year, month.month)[1])
    stmt = await account_statement(session, viewer_id, acc.id, start, end)
    income = expense = transfer = 0
    by_cat: dict[UUID | None, int] = defaultdict(int)
    for it in stmt.items:
        if it.type == "income":
            income += it.amount_cents
        elif it.type == "expense":
            expense += -it.amount_cents
            by_cat[it.category_id] += -it.amount_cents
        else:
            transfer += it.amount_cents
    mine = select(SpaceMember.space_id).where(SpaceMember.user_id == viewer_id)
    pockets = list(
        await session.scalars(
            select(Pocket).where(Pocket.account_id == acc.id, Pocket.closed_at.is_(None))
        )
    )
    pocket_ids = [p.id for p in pockets]
    goals = list(
        await session.scalars(
            select(Goal)
            .where(
                Goal.space_id.in_(mine),
                or_(
                    Goal.id.in_(
                        select(GoalAccount.goal_id).where(GoalAccount.account_id == acc.id)
                    ),
                    Goal.id.in_(
                        select(GoalPocket.goal_id).where(GoalPocket.pocket_id.in_(pocket_ids))
                    ),
                ),
            )
            .order_by(Goal.name)
        )
    )
    default_id = await session.scalar(
        select(SpaceMember.default_account_id).where(
            SpaceMember.user_id == viewer_id, SpaceMember.space_id == acc.space_id
        )
    )
    return {
        "month": start,
        "is_default": default_id == acc.id,
        "income_cents": income,
        "expense_cents": expense,
        "transfer_net_cents": transfer,
        "private_total_cents": stmt.private_total_cents,
        "by_category": [
            {"category_id": k, "total_cents": v}
            for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])
        ],
        "recent": [
            {
                "occurred_on": it.occurred_on,
                "type": it.type,
                "description": it.description,
                "merchant": it.merchant,
                "amount_cents": it.amount_cents,
            }
            for it in sorted(stmt.items, key=lambda x: x.occurred_on, reverse=True)[:10]
        ],  # fmt: skip
        "pockets": [
            {
                "id": p.id,
                "name": p.name,
                "balance_cents": (await pocket_stats(session, p.id, today)).balance,
            }
            for p in pockets
        ],  # fmt: skip
        "goals": [{"id": g.id, "name": g.name} for g in goals],
    }
