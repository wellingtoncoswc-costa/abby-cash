from datetime import date, datetime
from decimal import Decimal

import httpx
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.pockets.models import CdiRate

SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados"


class SgsRow(BaseModel):
    data: date  # "24/11/2026"
    valor: Decimal  # "0.055131" = % ao dia

    @field_validator("data", mode="before")
    @classmethod
    def _br_date(cls, v: str) -> date:
        return datetime.strptime(v, "%d/%m/%Y").date()


async def fetch_cdi(since: date, transport: httpx.AsyncBaseTransport | None = None) -> list[SgsRow]:
    """CDI diário do Banco Central (SGS 12). Sem redirect; formato inválido falha."""
    async with httpx.AsyncClient(timeout=10, follow_redirects=False, transport=transport) as c:
        r = await c.get(SGS_URL, params={"formato": "json", "dataInicial": f"{since:%d/%m/%Y}"})
        r.raise_for_status()
        return [SgsRow.model_validate(x) for x in r.json()]


async def upsert_cdi(session: AsyncSession, rows: list[SgsRow]) -> None:
    for r in rows:
        await session.execute(
            insert(CdiRate)
            .values(on_date=r.data, daily_pct=r.valor)
            .on_conflict_do_update(index_elements=["on_date"], set_={"daily_pct": r.valor})
        )
    await session.commit()


async def latest_cdi(session: AsyncSession) -> CdiRate | None:
    return await session.scalar(select(CdiRate).order_by(CdiRate.on_date.desc()).limit(1))


def annual_pct(daily_pct: Decimal) -> Decimal:
    """((1 + d/100)^252 - 1) x 100, só para exibir."""
    return ((1 + daily_pct / 100) ** 252 - 1) * 100
