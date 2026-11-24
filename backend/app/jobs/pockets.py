import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from app.channels.sender import notify_user
from app.core.config import get_settings
from app.core.dates import local_today
from app.core.db import SessionLocal
from app.core.redis import redis
from app.domain.pockets.cdi import fetch_cdi, upsert_cdi
from app.domain.pockets.models import CdiRate, Pocket
from app.domain.pockets.service import accrue_all
from app.domain.users.models import User
from app.jobs.scheduler import isolated

log = logging.getLogger(__name__)
FAIL_KEY, ALERT_KEY, FAIL_LIMIT = "cdi:fails", "cdi:alerted", 3
ALERT = "⚠️ Não consegui buscar o CDI no Banco Central ({n} falhas seguidas). Rendimentos pausados."


def last_business_day(today: date) -> date:
    d = today - timedelta(days=1)
    while d.weekday() > 4:
        d -= timedelta(days=1)
    return d


async def _alert_admins() -> None:
    async with SessionLocal() as s:
        admins = list(await s.scalars(select(User.id).where(User.is_admin)))
    for uid in admins:
        await notify_user(uid, ALERT.format(n=FAIL_LIMIT), prefer="telegram")


async def sync_cdi_job(
    ctx: dict[str, Any] | None = None, *, today: date | None = None, transport: Any = None
) -> None:
    """Cron horário (08:30 SP em diante): busca o CDI se falta o último dia útil, credita o
    rendimento das caixinhas e lança as receitas mensais. Feriado: refaz a busca a cada hora
    (barata). 3 falhas seguidas avisam os admins uma vez.
    # ponytail: sem calendário de feriados; se o BCB não publicar, só repete a consulta."""
    today = today or local_today(get_settings().DEFAULT_TZ)
    async with SessionLocal() as s:
        have = await s.scalar(select(func.max(CdiRate.on_date)))
    if have is None or have < last_business_day(today):
        try:
            rows = await fetch_cdi(have or today - timedelta(days=30), transport)
            async with SessionLocal() as s:
                await upsert_cdi(s, rows)
            await redis.delete(FAIL_KEY, ALERT_KEY)
        except Exception as e:
            log.warning("cdi fetch failed (%s)", type(e).__name__)
            if await redis.incr(FAIL_KEY) >= FAIL_LIMIT and await redis.set(
                ALERT_KEY, "1", nx=True, ex=86400
            ):
                await _alert_admins()
    async with SessionLocal() as s:
        ids = list(await s.scalars(select(Pocket.id).where(Pocket.closed_at.is_(None))))
    for pid in ids:
        await isolated("pocket", lambda pid=pid: _accrue(pid, today))  # type: ignore[misc]


async def _accrue(pid: Any, today: date) -> None:
    async with SessionLocal() as s:
        await accrue_all(s, pid, today)
