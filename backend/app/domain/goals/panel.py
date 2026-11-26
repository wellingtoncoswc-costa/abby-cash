from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.models import Account
from app.domain.goals.service import goal_links, goal_saved, goal_total, visible_goal
from app.domain.pockets.models import Pocket
from app.domain.pockets.service import pocket_stats
from app.domain.transactions.models import Transaction
from app.domain.transactions.service import account_balance


async def goal_panel(
    session: AsyncSession, viewer_id: UUID, goal_id: UUID, *, today: date
) -> dict[str, Any]:  # fmt: skip
    """De onde vem o progresso: aportes diretos, contas e caixinhas ligadas (a caixinha de uma
    conta já ligada aparece com `counted=False`: o saldo da conta já a inclui)."""
    goal = await visible_goal(session, viewer_id, goal_id)
    acc_ids, pk_ids = await goal_links(session, goal.id)
    accounts = [
        {"id": a.id, "name": a.name, "balance_cents": await account_balance(session, a.id)}
        for a in await session.scalars(select(Account).where(Account.id.in_(acc_ids)))
    ]
    pockets = []
    for p in await session.scalars(select(Pocket).where(Pocket.id.in_(pk_ids))):
        pockets.append({
            "id": p.id, "name": p.name,
            "balance_cents": (await pocket_stats(session, p.id, today)).balance,
            "counted": p.account_id not in acc_ids,
        })  # fmt: skip
    txs = await session.scalars(
        select(Transaction)
        .where(Transaction.goal_id == goal.id)
        .order_by(Transaction.occurred_on.desc(), Transaction.created_at.desc())
        .limit(10)
    )
    return {
        "total_cents": await goal_total(session, goal.id, today),
        "direct_cents": await goal_saved(session, goal.id),
        "accounts": accounts,
        "pockets": pockets,
        "contributions": [
            {
                "occurred_on": t.occurred_on,
                "direction": t.goal_direction,
                "amount_cents": t.amount_cents,
            }
            for t in txs
        ],  # fmt: skip
    }
