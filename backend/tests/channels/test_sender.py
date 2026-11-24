import pytest
from sqlalchemy import select

from app.channels import registry
from app.channels.sender import notify_user
from app.domain.channels.models import OutboundMessage
from tests.assistant.fakes import FakeAdapter
from tests.factories import make_link, make_user


class Down(FakeAdapter):
    async def send_text(self, external_user_id: str, text: str) -> None:
        raise RuntimeError("whatsapp down")


@pytest.fixture
async def ana(session, monkeypatch):
    tg, wa = FakeAdapter(), Down()
    monkeypatch.setitem(registry._adapters, "telegram", tg)
    monkeypatch.setitem(registry._adapters, "whatsapp_evolution", wa)
    user = await make_user(session, "ana@x.com")
    await make_link(session, user, "111")
    await make_link(session, user, "5511988887777", "whatsapp_evolution")
    return user, tg, wa


async def rows(session):
    return [(r.channel, r.status, r.error_kind) for r in await session.scalars(
        select(OutboundMessage).order_by(OutboundMessage.created_at)
    )]  # fmt: skip


async def test_fallback_to_telegram_on_whatsapp_failure(session, ana):
    user, tg, _ = ana
    assert await notify_user(user.id, "oi", prefer="whatsapp_evolution") == "telegram"
    assert tg.sent == [("111", "oi")]
    assert await rows(session) == [
        ("whatsapp_evolution", "failed", "RuntimeError"), ("telegram", "ok", None),
    ]  # fmt: skip


async def test_preferred_channel_first_and_stops_on_success(session, ana):
    user, tg, _ = ana
    assert await notify_user(user.id, "oi", prefer="telegram") == "telegram"
    assert await rows(session) == [("telegram", "ok", None)]


async def test_all_channels_failing_or_none_linked_returns_none(session, ana, monkeypatch):
    user, _, _ = ana
    monkeypatch.setitem(registry._adapters, "telegram", Down())
    assert await notify_user(user.id, "oi") is None
    assert len(await rows(session)) == 2
    other = await make_user(session, "bia@x.com")
    assert await notify_user(other.id, "oi") is None
