from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, NamedTuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import add_months
from app.domain.budgets.models import Budget, BudgetAlertSent, BudgetCategory
from app.domain.cards.models import Invoice
from app.domain.spaces.access import require_member
from app.domain.transactions.models import Transaction
from app.domain.transactions.rules import check_common


@dataclass(frozen=True)
class BudgetAlert:
    scope: Literal["general", "category"]
    category_id: UUID | None
    threshold: int  # 80 | 100 | 101 (101 = acima do teto)
    spent: int
    limit: int


class FutureImpact(NamedTuple):
    month: date
    spent: int
    limit: int | None  # None: o mês ainda não tem teto


def _bounds(month: date) -> tuple[date, date]:
    start = month.replace(day=1)
    return start, add_months(start, 1)


async def month_spending(
    session: AsyncSession, space_id: UUID, month: date, category_id: UUID | None = None
) -> int:
    """Despesas fora do cartão (data no mês) + compras de cartão cuja fatura vence no mês.

    Transferências (pagamento de fatura, aportes em metas) não são `expense`: nunca entram."""
    start, end = _bounds(month)
    t = Transaction
    by_cat = [] if category_id is None else [t.category_id == category_id]
    total = func.coalesce(func.sum(t.amount_cents), 0)
    cash = await session.scalar(
        select(total).where(
            t.space_id == space_id, t.type == "expense", t.card_id.is_(None),
            t.occurred_on >= start, t.occurred_on < end, *by_cat,
        )
    )  # fmt: skip
    card = await session.scalar(
        select(total)
        .select_from(t)
        .join(Invoice, Invoice.id == t.invoice_id)
        .where(
            t.space_id == space_id, t.type == "expense", t.card_id.is_not(None),
            Invoice.due_on >= start, Invoice.due_on < end, *by_cat,
        )
    )  # fmt: skip
    return int(cash or 0) + int(card or 0)


async def set_budget(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, month: date, limit_cents: int,
    categories: dict[UUID, int] | None = None,
) -> Budget:  # fmt: skip
    """Cria/atualiza o teto do mês (geral + por categoria; as categorias são substituídas)."""
    await require_member(session, actor_id, space_id)
    for cid, limit in (categories or {}).items():
        await check_common(
            session, actor_id=actor_id, space_id=space_id, type="expense", amount_cents=limit,
            category_id=cid, occurred_on=month,
        )  # fmt: skip
    await check_common(
        session, actor_id=actor_id, space_id=space_id, type="expense", amount_cents=limit_cents,
        category_id=None, occurred_on=month,
    )  # fmt: skip
    start = month.replace(day=1)
    budget = await session.scalar(
        select(Budget).where(Budget.space_id == space_id, Budget.month == start)
    )
    if budget is None:
        budget = Budget(space_id=space_id, month=start, limit_cents=limit_cents)
        session.add(budget)
        await session.flush()
    else:
        # ponytail: alertas já enviados não são zerados ao mudar o teto; resetar se o dono pedir
        budget.limit_cents = limit_cents
    await session.execute(delete(BudgetCategory).where(BudgetCategory.budget_id == budget.id))
    for cid, limit in (categories or {}).items():
        session.add(BudgetCategory(budget_id=budget.id, category_id=cid, limit_cents=limit))
    await session.commit()
    return budget


async def budget_overview(
    session: AsyncSession, *, viewer_id: UUID, space_id: UUID, month: date
) -> dict[str, Any]:
    await require_member(session, viewer_id, space_id)
    start = month.replace(day=1)
    budget = await session.scalar(
        select(Budget).where(Budget.space_id == space_id, Budget.month == start)
    )
    if budget is None:
        raise HTTPException(status_code=404, detail="budget_not_found")
    cats = await session.scalars(
        select(BudgetCategory).where(BudgetCategory.budget_id == budget.id)
    )
    return {
        "month": start,
        "limit_cents": budget.limit_cents,
        "spent_cents": await month_spending(session, space_id, start),
        "categories": [
            {
                "category_id": c.category_id,
                "limit_cents": c.limit_cents,
                "spent_cents": await month_spending(session, space_id, start, c.category_id),
            }
            for c in cats
        ],
    }


def _crossed(spent: int, limit: int) -> list[int]:
    hits = ((80, spent * 100 >= limit * 80), (100, spent >= limit), (101, spent > limit))
    return [threshold for threshold, hit in hits if hit]


async def evaluate_thresholds(
    session: AsyncSession, space_id: UUID, month: date
) -> list[BudgetAlert]:
    """Limiares novos: registra todos e devolve só o mais alto por escopo."""
    start = month.replace(day=1)
    budget = await session.scalar(
        select(Budget).where(Budget.space_id == space_id, Budget.month == start)
    )
    if budget is None:
        return []
    cats = await session.scalars(
        select(BudgetCategory).where(BudgetCategory.budget_id == budget.id)
    )
    scopes: list[tuple[UUID | None, int]] = [(None, budget.limit_cents)]
    scopes += [(c.category_id, c.limit_cents) for c in cats]
    alerts: list[BudgetAlert] = []
    for cat_id, limit in scopes:
        key = "general" if cat_id is None else str(cat_id)
        spent = await month_spending(session, space_id, start, cat_id)
        # unique + ON CONFLICT DO NOTHING: em corrida só quem insere devolve o alerta
        rows = [
            {"space_id": space_id, "month": start, "scope_key": key, "threshold": t}
            for t in _crossed(spent, limit)
        ]
        stmt = insert(BudgetAlertSent).on_conflict_do_nothing(constraint="uq_budget_alert_once")
        new = (
            list(await session.scalars(stmt.values(rows).returning(BudgetAlertSent.threshold)))
            if rows
            else []
        )
        if new:
            scope: Literal["general", "category"] = "general" if cat_id is None else "category"
            alerts.append(BudgetAlert(scope, cat_id, max(new), spent, limit))
    await session.commit()
    return alerts


async def future_impact(
    session: AsyncSession, space_id: UUID, transactions: Sequence[Transaction]
) -> list[FutureImpact]:
    """Por mês de vencimento das compras de cartão dadas: gasto atual e teto (se houver)."""
    ids = {t.invoice_id for t in transactions if t.invoice_id is not None}
    if not ids:
        return []
    dues = await session.scalars(select(Invoice.due_on).where(Invoice.id.in_(ids)))
    out: list[FutureImpact] = []
    for month in sorted({d.replace(day=1) for d in dues}):
        limit = await session.scalar(
            select(Budget.limit_cents).where(Budget.space_id == space_id, Budget.month == month)
        )
        out.append(FutureImpact(month, await month_spending(session, space_id, month), limit))
    return out
