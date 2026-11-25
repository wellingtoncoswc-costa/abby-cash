from datetime import date

from sqlalchemy import select

from app.core.db import SessionLocal
from app.domain.investments import service as svc
from app.domain.investments.models import PriceQuote
from app.domain.investments.quotes import Quote
from app.jobs import investments as job
from tests.factories import make_user


async def test_sync_quotes_is_idempotent_and_survives_one_failure(session, monkeypatch):
    a = await make_user(session, "a@x.com")

    async def ok(ticker, days, transport=None):
        return [Quote(date(2026, 1, 15), 3850)]

    async def flaky(ticker, days, transport=None):
        if ticker == "BAD3":
            raise RuntimeError("brapi fora")
        return await ok(ticker, days)

    monkeypatch.setattr(svc, "fetch_quotes", ok)  # cadastro dos dois ativos
    for t in ("BAD3", "PETR4"):
        await svc.create_investment(
            session, actor_id=a.id, space_id=a.default_space_id, kind="stock", name=t,
            ticker=t, today=date(2026, 1, 15),
        )  # fmt: skip
    monkeypatch.setattr(job, "fetch_quotes", flaky)  # no job o BAD3 falha, o PETR4 segue
    await job.sync_quotes_job(today=date(2026, 1, 15))
    await job.sync_quotes_job(today=date(2026, 1, 15))
    async with SessionLocal() as s:
        rows = list(await s.scalars(select(PriceQuote).where(PriceQuote.ticker == "PETR4")))
    assert [(r.on_date, r.close_cents) for r in rows] == [(date(2026, 1, 15), 3850)]
