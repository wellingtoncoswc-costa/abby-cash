import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import (
    accounts,
    admin,
    attachments,
    auth,
    bills,
    budgets,
    cards,
    categories,
    channel_links,
    goals,
    investments,
    loans,
    me,
    pockets,
    privacy,
    projections,
    recurring,
    reports,
    spaces,
    transactions,
    webhooks,
)
from app.core.config import get_settings
from app.core.db import engine
from app.core.http import install
from app.core.redis import HEARTBEAT_KEY, redis
from app.domain.errors import DomainError

app = FastAPI(title="Abby Cash")
install(app)
app.include_router(auth.router)
app.include_router(spaces.router)
app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(cards.router)
app.include_router(bills.router)
app.include_router(budgets.router)
app.include_router(reports.router)
app.include_router(goals.router)
app.include_router(investments.router)
app.include_router(pockets.router)
app.include_router(projections.router)
app.include_router(recurring.router)
app.include_router(loans.router)
app.include_router(categories.router)
app.include_router(me.router)
app.include_router(admin.router)
app.include_router(attachments.router)
app.include_router(channel_links.router)
app.include_router(privacy.router)
app.include_router(webhooks.router)


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/health")
async def health() -> dict[str, object]:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        db = True
    except Exception:
        db = False
    try:
        redis_ok = bool(await redis.ping())
    except Exception:
        redis_ok = False
    age: int | None = None
    try:
        beat = await redis.get(HEARTBEAT_KEY)
        age = round(time.time() - float(beat)) if beat else None
    except Exception:
        pass
    worker = age is not None and age <= get_settings().HEARTBEAT_STALE_S
    return {
        "status": "ok" if db and redis_ok and worker else "degraded",
        "db": db,
        "redis": redis_ok,
        "worker": worker,
        "worker_last_seen_s": age,
    }
