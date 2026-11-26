import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.errors import DomainError
from app.domain.investments.models import PriceQuote

URL = "https://brapi.dev/api/quote/{ticker}"
TICKER = re.compile(r"[A-Z0-9]{4,12}")
RANGES = [(5, "5d"), (30, "1mo"), (90, "3mo"), (180, "6mo"), (365, "1y"), (730, "2y"),
          (1825, "5y"), (3650, "10y")]  # fmt: skip


class _Bar(BaseModel):
    date: int  # epoch em segundos
    close: Decimal | None = None


class _Result(BaseModel):
    historicalDataPrice: list[_Bar] = []  # noqa: N815 (nome do campo da brapi)


class _Resp(BaseModel):
    results: list[_Result] = []


@dataclass(frozen=True)
class Quote:
    on_date: date
    close_cents: int


def range_for(days: int) -> str:
    return next((r for d, r in RANGES if days <= d), "max")


async def fetch_quotes(
    ticker: str, days: int, transport: httpx.AsyncBaseTransport | None = None
) -> list[Quote]:
    """Fechamentos dos últimos `days` dias (brapi.dev). Sem redirect; formato inválido falha."""
    if not TICKER.fullmatch(ticker):
        raise DomainError("unknown_ticker")
    s = get_settings()
    async with httpx.AsyncClient(timeout=10, follow_redirects=False, transport=transport) as c:
        r = await c.get(
            URL.format(ticker=ticker),
            params={"range": range_for(days), "interval": "1d", "token": s.BRAPI_TOKEN},
        )
    if r.status_code == 404:
        raise DomainError("unknown_ticker")
    r.raise_for_status()
    data = _Resp.model_validate(json.loads(r.text, parse_float=Decimal))
    if not data.results:
        raise DomainError("unknown_ticker")
    tz = ZoneInfo(s.DEFAULT_TZ)
    return [
        Quote(
            datetime.fromtimestamp(b.date, tz).date(),
            int((b.close * 100).quantize(Decimal(1), ROUND_HALF_EVEN)),
        )
        for b in data.results[0].historicalDataPrice
        if b.close is not None
    ]


async def upsert_quotes(session: AsyncSession, ticker: str, quotes: list[Quote]) -> None:
    """Não faz commit."""
    for q in quotes:
        await session.execute(
            insert(PriceQuote)
            .values(ticker=ticker, on_date=q.on_date, close_cents=q.close_cents)
            .on_conflict_do_update(
                index_elements=["ticker", "on_date"], set_={"close_cents": q.close_cents}
            )
        )


async def latest_close(session: AsyncSession, ticker: str, on: date) -> PriceQuote | None:
    return (
        await session.scalars(
            select(PriceQuote)
            .where(PriceQuote.ticker == ticker, PriceQuote.on_date <= on)
            .order_by(PriceQuote.on_date.desc())
            .limit(1)
        )
    ).first()
