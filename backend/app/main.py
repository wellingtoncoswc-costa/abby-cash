from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import accounts, auth, bills, budgets, cards, spaces, transactions
from app.core.db import engine
from app.core.redis import redis
from app.domain.errors import DomainError

app = FastAPI(title="Abby Cash")
app.include_router(auth.router)
app.include_router(spaces.router)
app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(cards.router)
app.include_router(bills.router)
app.include_router(budgets.router)


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
    return {"status": "ok" if db and redis_ok else "degraded", "db": db, "redis": redis_ok}
