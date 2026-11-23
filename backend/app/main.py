from fastapi import FastAPI
from sqlalchemy import text

from app.api import auth
from app.core.db import engine
from app.core.redis import redis

app = FastAPI(title="Abby Cash")
app.include_router(auth.router)


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
