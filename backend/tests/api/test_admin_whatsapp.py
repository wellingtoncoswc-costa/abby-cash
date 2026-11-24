from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.channels.evolution import InstanceNotFound
from app.channels.telegram import ChannelError
from app.domain.audit import AuditLog
from tests.factories import auth, make_user

QR = "data:image/png;base64,AAAA"


class FakeEvo:
    def __init__(self, state="none"):
        self.state, self.calls = state, []

    async def connection_state(self):
        if self.state == "none":
            raise InstanceNotFound("x")
        if self.state == "down":
            raise ChannelError("x")
        return self.state

    async def create_instance(self):
        self.calls.append("create")
        self.state = "connecting"
        return QR

    async def connect_qr(self):
        self.calls.append("connect")
        return QR

    async def set_webhook(self, url, secret):
        self.calls.append(("webhook", url))

    async def logout(self):
        self.calls.append("logout")
        self.state = "close"


@pytest.fixture
def evo(monkeypatch):
    fake = FakeEvo()
    cfg = SimpleNamespace(
        EVOLUTION_URL="http://evo", EVOLUTION_API_KEY="k", EVOLUTION_INSTANCE="abby",
        EVOLUTION_WEBHOOK_SECRET="s", PUBLIC_BASE_URL="https://x.test/", EVOLUTION_WEBHOOK_URL="http://api:8000/webhooks/whatsapp_evolution",
    )  # fmt: skip
    monkeypatch.setattr("app.api.admin.get_settings", lambda: cfg)
    monkeypatch.setattr("app.api.admin.evolution_adapter", lambda: SimpleNamespace(client=fake))
    return fake


async def admin(session):
    u = await make_user(session, "adm@x.com")
    u.is_admin = True
    await session.commit()
    return u


async def test_only_admin(client, session, evo):
    u = await make_user(session, "a@x.com")
    for m, p in (
        ("get", "/admin/whatsapp"),
        ("post", "/admin/whatsapp/qr"),
        ("post", "/admin/whatsapp/logout"),
    ):
        assert (await getattr(client, m)(p, headers=auth(u))).status_code == 403
        assert (await getattr(client, m)(p)).status_code == 401
    assert evo.calls == []


async def test_qr_creates_instance_and_registers_webhook(client, session, evo):
    u = await admin(session)
    assert (await client.get("/admin/whatsapp", headers=auth(u))).json() == {
        "state": "none",
        "qr": None,
    }
    r = await client.post("/admin/whatsapp/qr", headers=auth(u))
    assert r.json() == {"state": "connecting", "qr": QR}
    assert evo.calls == ["create", ("webhook", "http://api:8000/webhooks/whatsapp_evolution")]
    r = await client.post("/admin/whatsapp/qr", headers=auth(u))  # já existe: só reconecta
    assert r.json()["qr"] == QR and evo.calls[-1] == "connect"
    assert "whatsapp.qr" in set(await session.scalars(select(AuditLog.action)))


async def test_qr_when_connected_returns_no_qr(client, session, evo):
    u = await admin(session)
    evo.state = "open"
    r = await client.post("/admin/whatsapp/qr", headers=auth(u))
    assert r.json() == {"state": "open", "qr": None} and evo.calls == []


async def test_logout_and_errors(client, session, evo):
    u = await admin(session)
    evo.state = "open"
    r = await client.post("/admin/whatsapp/logout", headers=auth(u))
    assert r.json()["state"] == "close" and evo.calls == ["logout"]
    evo.state = "down"
    assert (await client.get("/admin/whatsapp", headers=auth(u))).status_code == 502


async def test_not_configured(client, session, monkeypatch):
    u = await admin(session)
    monkeypatch.setattr(
        "app.api.admin.get_settings",
        lambda: SimpleNamespace(EVOLUTION_URL="", EVOLUTION_API_KEY="", EVOLUTION_INSTANCE=""),
    )
    assert (await client.get("/admin/whatsapp", headers=auth(u))).status_code == 503
