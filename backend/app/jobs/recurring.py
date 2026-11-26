import logging
from datetime import date
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.dates import local_today
from app.core.db import SessionLocal
from app.domain.recurring.models import RecurringItem
from app.domain.recurring.service import post_due

log = logging.getLogger(__name__)


async def post_recurring_job(
    ctx: dict[str, Any] | None = None, *, today: date | None = None
) -> None:
    """Lança as datas devidas dos fixos ativos (idempotente). Falha de um item não para os outros.
    # ponytail: dia calculado no fuso padrão (DEFAULT_TZ), não no de cada usuário"""
    today = today or local_today(get_settings().DEFAULT_TZ)
    async with SessionLocal() as s:
        ids = list(await s.scalars(select(RecurringItem.id).where(RecurringItem.active.is_(True))))
    for item_id in ids:
        try:
            async with SessionLocal() as s:
                item = await s.get(RecurringItem, item_id)
                if item is not None:
                    await post_due(s, item, today)
        except Exception:  # um item ruim (conta removida etc.) não derruba os demais
            log.warning("recurring post failed", extra={"item_id": str(item_id)})
