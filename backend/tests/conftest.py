import asyncio
import os

import asyncpg
from sqlalchemy.engine import make_url

from app.core.config import get_settings


def _isolate_test_infra() -> None:
    """Testes rodam em DB `<db>_test` e Redis DB 15: nunca no banco/cache de dev."""
    assert get_settings().ENV != "prod", "testes apagam o schema: nunca rode com ENV=prod"
    url = make_url(get_settings().DATABASE_URL)
    name = url.database or ""
    if not name.endswith("_test"):
        name += "_test"
    url = url.set(database=name)
    assert name.endswith("_test")

    async def _create() -> None:
        conn = await asyncpg.connect(
            user=url.username, password=url.password, host=url.host, port=url.port,
            database="postgres",
        )  # fmt: skip
        try:
            if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", name):
                await conn.execute(f'CREATE DATABASE "{name}"')
        finally:
            await conn.close()

    asyncio.run(_create())
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    os.environ["REDIS_URL"] = (
        make_url(get_settings().REDIS_URL).set(database=os.environ.get("TEST_REDIS_DB", "15")).render_as_string(hide_password=False)
    )
    get_settings.cache_clear()
    assert get_settings().DATABASE_URL.rsplit("/", 1)[-1].endswith("_test")


_isolate_test_infra()

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import app.domain.models  # noqa: F401
from app.core.db import Base, SessionLocal, engine
from app.core.redis import redis
from app.main import app


@pytest.fixture(scope="session", autouse=True)
async def _schema():
    assert get_settings().ENV != "prod", "testes apagam o schema: nunca rode com ENV=prod"
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
