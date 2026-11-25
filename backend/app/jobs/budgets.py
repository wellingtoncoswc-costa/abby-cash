import logging
from typing import Any

from sqlalchemy import select

from app.assistant.replies import alert_text
from app.channels.sender import notify_user
from app.core.config import get_settings
from app.core.dates import local_today
from app.core.db import SessionLocal
from app.domain.budgets.models import Budget
from app.domain.budgets.service import evaluate_thresholds
from app.domain.categories.models import Category
from app.domain.spaces.models import SpaceMember

log = logging.getLogger(__name__)


async def check_budget_thresholds(ctx: dict[str, Any] | None = None) -> None:
    """Cron diário de segurança: o chat já avisa na hora; aqui entram despesas de outros caminhos
    (web, recorrentes). `budget_alerts_sent` garante um aviso por limiar; alerta vai a TODOS os
    membros do espaço."""
    first = local_today(get_settings().DEFAULT_TZ).replace(day=1)
    async with SessionLocal() as s:
        pairs = list(
            await s.execute(select(Budget.space_id, Budget.month).where(Budget.month >= first))
        )
    for space_id, month in pairs:
        try:
            async with SessionLocal() as s:
                alerts = await evaluate_thresholds(s, space_id, month)
                names = {
                    c.id: c.name
                    for c in await s.scalars(select(Category).where(Category.space_id == space_id))
                }
                members = list(
                    await s.scalars(
                        select(SpaceMember.user_id).where(SpaceMember.space_id == space_id)
                    )
                )
            for a in alerts:
                text = alert_text(a, month, names.get(a.category_id) if a.category_id else None)
                for uid in members:
                    await notify_user(uid, text)
        except Exception as e:  # um espaço com problema não derruba os demais
            log.warning("budget threshold job failed for a space (%s)", type(e).__name__)
