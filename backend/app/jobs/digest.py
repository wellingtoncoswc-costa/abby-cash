import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.replies import month_name
from app.channels.sender import notify_user
from app.core.db import SessionLocal
from app.core.money import format_brl
from app.core.redis import redis
from app.domain.bills.models import Bill
from app.domain.budgets.models import Budget
from app.domain.budgets.service import month_spending
from app.domain.categories.models import Category
from app.domain.spaces.models import SpaceMember
from app.domain.transactions.models import Transaction
from app.domain.users.models import User

log = logging.getLogger(__name__)


async def build_digest(session: AsyncSession, user_id: UUID, today: date) -> str:
    """Só dados dos espaços de que o usuário é membro (lançamentos e contas de outros espaços,
    mesmo em conta compartilhada, nunca entram)."""
    spaces = list(
        await session.scalars(select(SpaceMember.space_id).where(SpaceMember.user_id == user_id))
    )
    start = today - timedelta(days=6)
    rows = (
        await session.execute(
            select(Category.name, func.sum(Transaction.amount_cents))
            .select_from(Transaction)
            .outerjoin(Category, Category.id == Transaction.category_id)
            .where(
                Transaction.space_id.in_(spaces), Transaction.type == "expense",
                Transaction.occurred_on >= start, Transaction.occurred_on <= today,
            )
            .group_by(Category.name)
        )
    ).all()  # fmt: skip
    total = sum(int(v) for _, v in rows)
    lines = [f"📅 Resumo da semana: {format_brl(total)} em gastos."]
    for name, v in sorted(rows, key=lambda r: -int(r[1]))[:3]:
        lines.append(f"• {name or 'Sem categoria'}: {format_brl(int(v))}")
    month = today.replace(day=1)
    limit = int(
        await session.scalar(
            select(func.coalesce(func.sum(Budget.limit_cents), 0)).where(
                Budget.space_id.in_(spaces), Budget.month == month
            )
        )
        or 0
    )
    if limit:
        budgeted = await session.scalars(
            select(Budget.space_id).where(Budget.space_id.in_(spaces), Budget.month == month)
        )
        spent = sum([await month_spending(session, sid, month) for sid in budgeted])
        lines.append(f"Teto de {month_name(month)}: {spent * 100 // limit}% usado.")
    bills = (
        await session.scalars(
            select(Bill)
            .where(
                Bill.space_id.in_(spaces), Bill.status != "paid",
                Bill.due_on >= today, Bill.due_on <= today + timedelta(days=7),
            )
            .order_by(Bill.due_on)
        )
    ).all()  # fmt: skip
    if bills:
        lines.append("Contas dos próximos 7 dias:")
        lines += [
            f"• {b.description} {format_brl(b.amount_cents)} — {b.due_on:%d/%m}" for b in bills
        ]
    return "\n".join(lines)


async def send_weekly_digests(
    ctx: dict[str, Any] | None = None, *, now: datetime | None = None
) -> None:
    """Cron de hora em hora: domingo 20h no fuso de cada usuário com `weekly_digest`. Um por
    usuário e semana ISO (chave no Redis; se nada foi entregue, libera para a próxima hora)."""
    now = now or datetime.now(UTC)
    async with SessionLocal() as s:
        users = list((await s.execute(select(User.id, User.tz).where(User.weekly_digest))).all())
    for uid, tz in users:
        try:
            local = now.astimezone(ZoneInfo(tz))
            if local.weekday() != 6 or local.hour != 20:
                continue
            y, w, _ = local.isocalendar()
            key = f"digest:{uid}:{y}-W{w}"
            if not await redis.set(key, "1", nx=True, ex=8 * 86400):
                continue
            async with SessionLocal() as s:
                text = await build_digest(s, uid, local.date())
            if not await notify_user(uid, text):
                await redis.delete(key)
        except Exception as e:
            log.warning("weekly digest failed for a user (%s)", type(e).__name__)
