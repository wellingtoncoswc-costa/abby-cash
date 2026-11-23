import asyncio
import time
from datetime import UTC, datetime, timedelta

import jwt
import pyotp

from app.domain.users.service import create_admin, create_signup_invite

PWD = "correct horse battery"


async def _invite(session) -> str:
    admin = await create_admin(session, email="admin@x.com", name="Admin", password=PWD)
    return (await create_signup_invite(session, created_by=admin.id)).code


async def _register(client, code, email="a@x.com"):
    return await client.post(
        "/auth/register",
        json={"email": email, "name": "A", "password": PWD, "invite_code": code},
    )


async def test_register_requires_valid_invite(client, session):
    assert (await _register(client, "nope")).status_code == 400
    code = await _invite(session)
    assert (await _register(client, code)).status_code == 201


async def test_invite_single_use(client, session):
    code = await _invite(session)
    assert (await _register(client, code, "a@x.com")).status_code == 201
    assert (await _register(client, code, "b@x.com")).status_code == 400


async def test_expired_invite_rejected(client, session):
    admin = await create_admin(session, email="admin@x.com", name="Admin", password=PWD)
    inv = await create_signup_invite(
        session, created_by=admin.id, expires_at=datetime.now(UTC) - timedelta(minutes=1)
    )
    assert (await _register(client, inv.code)).status_code == 400


async def test_login_rate_limited_after_5_failures(client, session):
    await _register(client, await _invite(session))
    for _ in range(5):
        r = await client.post("/auth/login", json={"email": "a@x.com", "password": "bad"})
        assert r.status_code == 401
    r = await client.post("/auth/login", json={"email": "a@x.com", "password": PWD})
    assert r.status_code == 429


async def test_unknown_email_same_error_and_counted(client):
    for _ in range(5):
        r = await client.post("/auth/login", json={"email": "ghost@x.com", "password": "bad"})
        assert r.status_code == 401 and r.json()["detail"] == "invalid_credentials"
    r = await client.post("/auth/login", json={"email": "ghost@x.com", "password": "bad"})
    assert r.status_code == 429


async def test_refresh_rotation_revokes_reused_token(client, session):
    await _register(client, await _invite(session))
    login = await client.post("/auth/login", json={"email": "a@x.com", "password": PWD})
    old = login.cookies["refresh_token"]
    sc = login.headers["set-cookie"].lower()
    assert "httponly" in sc and "secure" in sc and "samesite=lax" in sc
    r1 = await client.post("/auth/refresh", cookies={"refresh_token": old})
    assert r1.status_code == 200
    new = r1.cookies["refresh_token"]
    assert new != old
    # reuso do token antigo → 401 e a família inteira é revogada
    assert (await client.post("/auth/refresh", cookies={"refresh_token": old})).status_code == 401
    assert (await client.post("/auth/refresh", cookies={"refresh_token": new})).status_code == 401


async def test_2fa_required_when_enabled(client, session):
    await _register(client, await _invite(session))
    login = await client.post("/auth/login", json={"email": "a@x.com", "password": PWD})
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    secret = (await client.post("/auth/2fa/setup", headers=h)).json()["secret"]
    ok = await client.post("/auth/2fa/verify", headers=h, json={"code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200
    r = await client.post("/auth/login", json={"email": "a@x.com", "password": PWD})
    assert r.status_code == 401 and r.json()["detail"] == "totp_required"
    # código distinto do usado no verify (anti-replay), ainda dentro da janela
    r = await client.post(
        "/auth/login",
        json={"email": "a@x.com", "password": PWD, "totp": pyotp.TOTP(secret).at(time.time() + 30)},
    )
    assert r.status_code == 200


async def _enable_2fa(client):
    login = await client.post("/auth/login", json={"email": "a@x.com", "password": PWD})
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    secret = (await client.post("/auth/2fa/setup", headers=h)).json()["secret"]
    code = pyotp.TOTP(secret).now()
    assert (
        await client.post("/auth/2fa/verify", headers=h, json={"code": code})
    ).status_code == 200
    return h, secret, code


async def test_totp_code_cannot_be_replayed(client, session):
    await _register(client, await _invite(session))
    _, _, used = await _enable_2fa(client)
    r = await client.post("/auth/login", json={"email": "a@x.com", "password": PWD, "totp": used})
    assert r.status_code == 401


async def test_2fa_verify_brute_force_limited(client, session):
    await _register(client, await _invite(session))
    login = await client.post("/auth/login", json={"email": "a@x.com", "password": PWD})
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    await client.post("/auth/2fa/setup", headers=h)
    for _ in range(5):
        r = await client.post("/auth/2fa/verify", headers=h, json={"code": "000000"})
        assert r.status_code == 400
    r = await client.post("/auth/2fa/verify", headers=h, json={"code": "000000"})
    assert r.status_code == 429


async def test_short_password_rejected(client, session):
    code = await _invite(session)
    r = await client.post(
        "/auth/register",
        json={"email": "a@x.com", "name": "A", "password": "short", "invite_code": code},
    )
    assert r.status_code == 422


async def test_concurrent_same_invite_one_wins(client, session):
    code = await _invite(session)
    rs = await asyncio.gather(
        _register(client, code, "a@x.com"), _register(client, code, "b@x.com")
    )
    assert sorted(r.status_code for r in rs) == [201, 400]


async def test_concurrent_same_email_no_500(client, session):
    admin = await create_admin(session, email="admin@x.com", name="Admin", password=PWD)
    c1 = (await create_signup_invite(session, created_by=admin.id)).code
    c2 = (await create_signup_invite(session, created_by=admin.id)).code
    rs = await asyncio.gather(_register(client, c1), _register(client, c2))
    assert sorted(r.status_code for r in rs) == [201, 400]


async def test_garbage_and_expired_jwt_rejected(client):
    from app.core.config import get_settings
    from app.core.security import decode_access_token

    key = get_settings().JWT_SECRET
    bad = [
        "garbage",
        jwt.encode({"sub": "x", "exp": int(time.time()) - 10}, key, "HS256"),
        jwt.encode({"sub": "00000000-0000-0000-0000-000000000000"}, key, "HS256"),  # sem exp
    ]
    assert decode_access_token(bad[2]) is None
    for t in bad:
        r = await client.post("/auth/2fa/setup", headers={"Authorization": f"Bearer {t}"})
        assert r.status_code == 401


async def test_logout_revokes_refresh_family(client, session):
    await _register(client, await _invite(session))
    login = await client.post("/auth/login", json={"email": "a@x.com", "password": PWD})
    old = login.cookies["refresh_token"]
    assert (await client.post("/auth/logout", cookies={"refresh_token": old})).status_code == 204
    assert (await client.post("/auth/refresh", cookies={"refresh_token": old})).status_code == 401
    assert (await client.post("/auth/logout")).status_code == 204  # idempotente
