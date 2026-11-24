import pytest

from app.channels import registry
from app.core.config import get_settings
from app.core.redis import redis
from app.jobs.health import DOWN_KEY, check_evolution_connection
from tests.assistant.fakes import FakeAdapter
from tests.factories import make_link, make_user


class Evo:
    def __init__(self, state: str) -> None:
        self.state = state
        self.client = self

    async def connection_state(self) -> str:
        if self.state == "boom":
            raise RuntimeError("x")
        return self.state


@pytest.fixture
async def env(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "EVOLUTION_URL", "http://evo")
    tg, evo = FakeAdapter(), Evo("close")
    monkeypatch.setitem(registry._adapters, "telegram", tg)
    monkeypatch.setitem(registry._adapters, "whatsapp_evolution", evo)
    admin = await make_user(session, "adm@x.com")
    admin.is_admin = True
    await session.commit()
    await make_link(session, admin, "999")
    return tg, evo


async def test_disconnect_alert_once(env):
    tg, evo = env
    for _ in range(3):
        await check_evolution_connection({})
    assert len(tg.sent) == 1 and tg.sent[0][0] == "999" and "close" in tg.sent[0][1]
    evo.state = "open"  # voltou: fecha o incidente
    await check_evolution_connection({})
    assert await redis.get(DOWN_KEY) is None
    evo.state = "boom"  # novo incidente avisa de novo
    await check_evolution_connection({})
    await check_evolution_connection({})
    assert len(tg.sent) == 2


async def test_connected_or_unconfigured_sends_nothing(env, monkeypatch):
    tg, evo = env
    evo.state = "open"
    await check_evolution_connection({})
    monkeypatch.setattr(get_settings(), "EVOLUTION_URL", "")
    evo.state = "close"
    await check_evolution_connection({})
    assert tg.sent == []
