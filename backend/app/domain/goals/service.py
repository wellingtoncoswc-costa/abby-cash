from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import case, delete, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dates import local_today
from app.domain.accounts.access import use_account
from app.domain.audit import audit, snap
from app.domain.errors import DomainError
from app.domain.goals.models import Goal, GoalAccount, GoalPocket
from app.domain.pockets.models import Pocket
from app.domain.pockets.service import pocket_stats, visible_pocket
from app.domain.spaces.access import require_member, require_owner
from app.domain.transactions.models import Transaction
from app.domain.transactions.rules import check_common
from app.domain.transactions.service import account_balance


@dataclass(frozen=True)
class GoalProgress:
    saved: int
    target: int
    monthly_needed: int | None  # None: meta sem prazo
    behind: bool


async def create_goal(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, name: str, target_cents: int,
    created_on: date, deadline: date | None = None, account_ids: Sequence[UUID] = (),
    pocket_ids: Sequence[UUID] = (),
) -> Goal:  # fmt: skip
    await check_common(
        session, actor_id=actor_id, space_id=space_id, type="transfer", amount_cents=target_cents,
        category_id=None, occurred_on=created_on,
    )  # fmt: skip
    goal = Goal(
        space_id=space_id, name=name, target_cents=target_cents, deadline=deadline,
        created_on=created_on,
    )  # fmt: skip
    session.add(goal)
    await session.flush()
    await _set_links(session, actor_id, goal, list(account_ids), list(pocket_ids))
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
    """Aportes (goal_direction 'in') menos retiradas ('out')."""
    delta = case(
        (Transaction.goal_direction == "in", Transaction.amount_cents),
        else_=-Transaction.amount_cents,
    )
    total = await session.scalar(
        select(func.coalesce(func.sum(delta), 0)).where(Transaction.goal_id == goal_id)
    )
    return int(total or 0)


async def contribute(
    session: AsyncSession, *, actor_id: UUID, goal_id: UUID, from_account_id: UUID,
    amount_cents: int, on: date, origin: str = "web", source_message_id: str | None = None,
) -> Transaction:  # fmt: skip
    goal = await visible_goal(session, actor_id, goal_id)
    await check_common(
        session, actor_id=actor_id, space_id=goal.space_id, type="transfer",
        amount_cents=amount_cents, category_id=None, occurred_on=on,
    )  # fmt: skip
    await use_account(session, actor_id, from_account_id)
    tx = Transaction(
        space_id=goal.space_id, type="transfer", amount_cents=amount_cents, occurred_on=on,
        description=f"Aporte: {goal.name}", account_id=from_account_id, goal_id=goal.id,
        goal_direction="in",
        created_by=actor_id, origin=origin, source_message_id=source_message_id,
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
    await check_common(
        session, actor_id=actor_id, space_id=goal.space_id, type="transfer",
        amount_cents=amount_cents, category_id=None, occurred_on=on,
    )  # fmt: skip
    await use_account(session, actor_id, to_account_id)
    await session.refresh(goal, with_for_update=True)  # serializa retiradas da mesma meta
    if amount_cents > await goal_saved(session, goal.id):
        await session.rollback()  # solta o lock da meta
        raise DomainError("insufficient_saved")
    tx = Transaction(
        space_id=goal.space_id, type="transfer", amount_cents=amount_cents, occurred_on=on,
        description=f"Retirada: {goal.name}", account_id=None, counter_account_id=to_account_id,
        goal_id=goal.id, goal_direction="out", created_by=actor_id, origin="web",
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


async def goal_links(session: AsyncSession, goal_id: UUID) -> tuple[list[UUID], list[UUID]]:
    accs = await session.scalars(
        select(GoalAccount.account_id).where(GoalAccount.goal_id == goal_id)
    )
    pks = await session.scalars(select(GoalPocket.pocket_id).where(GoalPocket.goal_id == goal_id))
    return sorted(accs), sorted(pks)


async def _set_links(
    session: AsyncSession, actor_id: UUID, goal: Goal,
    account_ids: list[UUID] | None, pocket_ids: list[UUID] | None,
) -> None:  # fmt: skip
    """Substitui as ligações enviadas (None mantém). Conta/caixinha: uma meta só, inclusive
    cruzado (conta de uma meta + caixinha dessa conta em outra contaria o dinheiro duas vezes)."""
    cur_a, cur_p = await goal_links(session, goal.id)
    accs = set(cur_a if account_ids is None else account_ids)
    pids = set(cur_p if pocket_ids is None else pocket_ids)
    for aid in accs:
        await use_account(session, actor_id, aid)
    pockets = [await visible_pocket(session, actor_id, pid) for pid in pids]
    other_accs = set(
        await session.scalars(select(GoalAccount.account_id).where(GoalAccount.goal_id != goal.id))
    )
    other_pk = (
        await session.execute(
            select(GoalPocket.pocket_id, Pocket.account_id)
            .join(Pocket, Pocket.id == GoalPocket.pocket_id)
            .where(GoalPocket.goal_id != goal.id)
        )
    ).all()
    if accs & ({r[1] for r in other_pk} | other_accs) or any(
        p.id in {r[0] for r in other_pk} or p.account_id in other_accs for p in pockets
    ):
        raise DomainError("already_linked")
    await session.execute(delete(GoalAccount).where(GoalAccount.goal_id == goal.id))
    await session.execute(delete(GoalPocket).where(GoalPocket.goal_id == goal.id))
    session.add_all(GoalAccount(goal_id=goal.id, account_id=a) for a in accs)
    session.add_all(GoalPocket(goal_id=goal.id, pocket_id=p) for p in pids)
    try:
        await session.flush()
    except IntegrityError:  # corrida: outra meta pegou a mesma conta/caixinha
        await session.rollback()
        raise DomainError("already_linked") from None


async def goal_total(session: AsyncSession, goal_id: UUID, today: date) -> int:
    """Aportes diretos + saldo das contas ligadas + caixinhas ligadas (a caixinha de uma conta
    já ligada é ignorada: o saldo da conta já a inclui)."""
    accs, pids = await goal_links(session, goal_id)
    total = await goal_saved(session, goal_id)
    for a in accs:
        total += await account_balance(session, a)
    covered = set(await session.scalars(select(Pocket.id).where(Pocket.account_id.in_(accs))))
    for p in set(pids) - covered:
        total += (await pocket_stats(session, p, today)).balance
    return total


async def goal_progress(
    session: AsyncSession, goal_id: UUID, *, today: date | None = None
) -> GoalProgress:
    """`monthly_needed` = falta / meses até o prazo (mín. 1, arredondado p/ cima).
    `behind` = guardado < esperado por um ritmo linear de `created_on` até o prazo."""
    goal = await session.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="not_found")
    today = today or local_today(get_settings().DEFAULT_TZ)
    saved = await goal_total(session, goal.id, today)
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


async def update_goal(
    session: AsyncSession, *, actor_id: UUID, goal_id: UUID, fields: dict[str, Any]
) -> Goal:
    """fields: só as chaves enviadas (name, target_cents, deadline)."""
    goal = await visible_goal(session, actor_id, goal_id)
    await require_owner(session, actor_id, goal.space_id)
    ids = {k: fields.pop(k) for k in ("account_ids", "pocket_ids") if k in fields}
    if ids:
        await _set_links(session, actor_id, goal, ids.get("account_ids"), ids.get("pocket_ids"))
    before = snap(goal, fields)
    if "target_cents" in fields:
        await check_common(
            session, actor_id=actor_id, space_id=goal.space_id, type="transfer",
            amount_cents=fields["target_cents"], category_id=None, occurred_on=goal.created_on,
        )  # fmt: skip
    for k, v in fields.items():
        setattr(goal, k, v)
    audit(session, actor_id, "goal.update", "goal", goal.id,
          {"space_id": str(goal.space_id), "before": before,
           "after": snap(goal, fields)})  # fmt: skip
    await session.commit()
    return goal


async def delete_goal(session: AsyncSession, *, actor_id: UUID, goal_id: UUID) -> None:
    """Só meta zerada e sem histórico de aportes/retiradas (retire o saldo antes)."""
    goal = await visible_goal(session, actor_id, goal_id)
    await require_owner(session, actor_id, goal.space_id)
    await session.refresh(goal, with_for_update=True)
    if await goal_saved(session, goal.id) != 0:
        raise DomainError("goal_has_balance")
    if await session.scalar(select(exists().where(Transaction.goal_id == goal.id))):
        raise DomainError("goal_has_history")
    audit(session, actor_id, "goal.delete", "goal", goal.id, {"space_id": str(goal.space_id)})
    await session.delete(goal)
    await session.commit()
