import logging
from datetime import date
from typing import Any

from sqlalchemy import select

from app.channels.sender import notify_user
from app.core.config import get_settings
from app.core.dates import local_today
from app.core.db import SessionLocal
from app.core.money import format_brl
from app.core.redis import redis
from app.domain.goals.models import Goal
from app.domain.goals.service import goal_progress
from app.domain.spaces.models import SpaceMember

log = logging.getLogger(__name__)


async def notify_goals_behind(
    ctx: dict[str, Any] | None = None, *, today: date | None = None
) -> None:
    """Cron diário (~09:00 local): só no dia 1 avisa as metas atrasadas, uma vez por meta e mês
    (chave no Redis; se ninguém recebeu, libera para a próxima execução)."""
    today = today or local_today(get_settings().DEFAULT_TZ)
    if today.day != 1:
        return
    async with SessionLocal() as s:
        goals = list(await s.scalars(select(Goal).where(Goal.deadline.is_not(None))))
    for g in goals:
        key = f"goal-behind:{g.id}:{today:%Y-%m}"
        try:
            async with SessionLocal() as s:
                p = await goal_progress(s, g.id, today=today)
                members = list(
                    await s.scalars(
                        select(SpaceMember.user_id).where(SpaceMember.space_id == g.space_id)
                    )
                )
            if not p.behind or p.monthly_needed is None:
                continue
            if not await redis.set(key, "1", nx=True, ex=40 * 86400):
                continue
            text = (
                f"📌 A meta {g.name} está atrasada: {format_brl(p.saved)} de "
                f"{format_brl(p.target)}. Para chegar no prazo, guarde "
                f"{format_brl(p.monthly_needed)} por mês."
            )
            sent = [await notify_user(uid, text) for uid in members]
            if not any(sent):
                await redis.delete(key)
        except Exception as e:
            log.warning("goal behind job failed for a goal (%s)", type(e).__name__)
