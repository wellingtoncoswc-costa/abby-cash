from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_health_reports_db_and_redis():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": True, "redis": True}
