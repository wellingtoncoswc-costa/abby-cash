import logging
from datetime import date
from typing import Any

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.dates import local_today
from app.core.db import SessionLocal
from app.domain.investments.models import Investment, PriceQuote
from app.domain.investments.quotes import fetch_quotes, upsert_quotes

log = logging.getLogger(__name__)


async def sync_quotes_job(
    ctx: dict[str, Any] | None = None, *, today: date | None = None, transport: Any = None
) -> None:
    """Fechamento de cada ticker em carteira (idempotente); falha de um não para os outros."""
    today = today or local_today(get_settings().DEFAULT_TZ)
    async with SessionLocal() as s:
        tickers = list(
            await s.scalars(
                select(Investment.ticker).where(Investment.ticker.is_not(None)).distinct()
            )
        )
    for t in filter(None, tickers):
        try:
            async with SessionLocal() as s:
                last = await s.scalar(
                    select(func.max(PriceQuote.on_date)).where(PriceQuote.ticker == t)
                )
                days = (today - last).days + 5 if last else 30
                await upsert_quotes(s, t, await fetch_quotes(t, days, transport))
                await s.commit()
        except Exception:  # um ticker ruim não derruba os demais
            log.warning("quote sync failed", extra={"ticker": t})
