import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import app.domain.accounts.models  # noqa: F401
import app.domain.categories.models  # noqa: F401
import app.domain.spaces.models  # noqa: F401
import app.domain.users.models  # noqa: F401
from app.core.db import Base, SessionLocal, engine
from app.core.redis import redis
from app.main import app


@pytest.fixture(scope="session", autouse=True)
async def _schema():
    async with engine.begin() as conn:
        # schema inteiro: drop_all falha se o banco tem FK use_alter de um estado antigo
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture(autouse=True)
async def _clean():
    async with engine.begin() as conn:
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await redis.flushdb()


@pytest.fixture
async def session():
    async with SessionLocal() as s:
        yield s


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        yield c
