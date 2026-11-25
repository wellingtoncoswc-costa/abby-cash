import logging
import time
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from sqlalchemy import select, text
from starlette.requests import Request

from app.core.config import get_settings
from app.core.http import client_ip
from app.core.redis import HEARTBEAT_KEY, redis
from app.domain.users.models import RefreshToken
from app.jobs.scheduler import purge_refresh_tokens_job, worker_heartbeat
from tests.factories import make_user


def _req(peer: str, xff: str | None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1)})


def test_client_ip_ignores_xff_without_trusted_proxy(monkeypatch):
    monkeypatch.setattr(get_settings(), "TRUSTED_PROXIES", "")
    assert client_ip(_req("10.0.0.1", "6.6.6.6")) == "10.0.0.1"


def test_client_ip_uses_xff_only_from_trusted_peer(monkeypatch):
    monkeypatch.setattr(get_settings(), "TRUSTED_PROXIES", "172.18.0.0/16")
    assert client_ip(_req("172.18.0.1", "1.2.3.4")) == "1.2.3.4"
    assert client_ip(_req("172.18.0.1", "6.6.6.6, 1.2.3.4")) == "1.2.3.4"  # forjado à esquerda
    assert client_ip(_req("9.9.9.9", "1.2.3.4")) == "9.9.9.9"  # peer não confiável
    assert client_ip(_req("172.18.0.1", "lixo")) == "172.18.0.1"


async def test_login_limiter_keys_use_forwarded_ip_from_trusted_proxy(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "TRUSTED_PROXIES", "127.0.0.1/32")
    await client.post(
        "/auth/login", json={"email": "a@x.com", "password": "bad"},
        headers={"X-Forwarded-For": "8.8.4.4"},
    )  # fmt: skip
    assert await redis.exists("login_fail_ip:8.8.4.4")


async def test_security_headers_request_id_and_log_without_query(client, caplog):
    caplog.set_level(logging.INFO, logger="app.access")
    r = await client.get("/health?token=SEGREDO", headers={"X-Request-ID": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" not in r.headers
    assert "SEGREDO" not in caplog.text and any(x.path == "/health" for x in caplog.records)
    bad = await client.get("/health", headers={"X-Request-ID": "x y\n<script>"})
    assert bad.headers["x-request-id"] != "x y\n<script>"


async def test_hsts_only_when_enabled(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "HSTS", True)
    assert "max-age" in (await client.get("/health")).headers["strict-transport-security"]


async def test_health_degraded_without_fresh_worker_heartbeat(client):
    j = (await client.get("/health")).json()
    assert j["status"] == "degraded" and j["worker"] is False and j["worker_last_seen_s"] is None
    await worker_heartbeat()
    j = (await client.get("/health")).json()
    assert j["status"] == "ok" and j["worker"] is True and j["worker_last_seen_s"] <= 2
    await redis.set(HEARTBEAT_KEY, time.time() - 600)
    r = await client.get("/health")
    assert r.status_code == 200 and r.json()["worker"] is False


async def test_webhook_is_rate_limited_per_ip(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "WEBHOOK_RATE_PER_MIN", 2)
    codes = [(await client.post("/webhooks/telegram", content=b"{}")).status_code for _ in range(3)]
    assert codes[2] == 429 and 429 not in codes[:2]


async def test_totp_secret_is_encrypted_at_rest_and_legacy_plain_still_reads(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "TOTP_ENC_KEY", Fernet.generate_key().decode())
    u = await make_user(session, "t@x.com")
    u.totp_secret = "JBSWY3DPEHPK3PXP"
    await session.commit()
    raw = (
        await session.execute(text("select totp_secret from users where id=:i"), {"i": u.id})
    ).scalar()
    assert raw.startswith("enc:") and "JBSWY3DPEHPK3PXP" not in raw
    await session.refresh(u)
    assert u.totp_secret == "JBSWY3DPEHPK3PXP"
    await session.execute(
        text("update users set totp_secret='LEGACYPLAIN' where id=:i"), {"i": u.id}
    )
    await session.commit()
    await session.refresh(u)
    assert u.totp_secret == "LEGACYPLAIN"
    u.totp_secret = "NEWSECRET"  # escrever cifra
    await session.commit()
    raw = (
        await session.execute(text("select totp_secret from users where id=:i"), {"i": u.id})
    ).scalar()
    assert raw.startswith("enc:")


async def test_purge_refresh_tokens_removes_expired_and_old_revoked_only(session):
    u = await make_user(session, "r@x.com")
    now = datetime.now(UTC)

    def tok(h, exp, rev=None):
        return RefreshToken(
            user_id=u.id, family_id=u.id, token_hash=h, expires_at=exp, revoked_at=rev
        )

    session.add_all([
        tok("a" * 64, now - timedelta(days=1)),
        tok("b" * 64, now + timedelta(days=5), now - timedelta(days=2)),
        tok("c" * 64, now + timedelta(days=5), now - timedelta(hours=1)),
        tok("d" * 64, now + timedelta(days=5)),
    ])  # fmt: skip
    await session.commit()
    await purge_refresh_tokens_job()
    left = (await session.execute(select(RefreshToken.token_hash))).scalars().all()
    assert sorted(left) == ["c" * 64, "d" * 64]
