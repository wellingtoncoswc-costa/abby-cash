import pytest
from sqlalchemy import select

from app.channels.telegram import ChannelError, TelegramAdapter
from app.core.config import get_settings
from app.domain.channels.linking import link_with_code
from app.domain.channels.models import ChannelLink
from tests.factories import auth, make_user


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(get_settings(), "TELEGRAM_BOT_USERNAME", "")

    async def name(self) -> str:
        return "abby_bot"

    monkeypatch.setattr(TelegramAdapter, "bot_username", name)


async def test_link_code_returns_code_and_deep_link(client, session, bot):
    ana = await make_user(session, "ana@x.com")
    r = await client.post("/channels/link-code", json={"channel": "telegram"}, headers=auth(ana))
    assert r.status_code == 200
    body = r.json()
    assert len(body["code"]) == 6 and body["expires_in_s"] == 600
    assert body["deep_link"] == f"https://t.me/abby_bot?start={body['code']}"
    # o código criado vincula de verdade
    assert await link_with_code(
        session, channel="telegram", external_user_id="111", code=body["code"]
    )


async def test_link_code_without_bot_name_still_returns_code(client, session, monkeypatch):
    monkeypatch.setattr(get_settings(), "TELEGRAM_BOT_USERNAME", "")

    async def boom(self) -> str:
        raise ChannelError("telegram getMe failed")

    monkeypatch.setattr(TelegramAdapter, "bot_username", boom)
    ana = await make_user(session, "ana@x.com")
    r = await client.post("/channels/link-code", json={"channel": "telegram"}, headers=auth(ana))
    assert r.status_code == 200 and r.json()["deep_link"] is None


async def test_link_code_requires_auth_and_valid_channel(client, session, bot):
    assert (
        await client.post("/channels/link-code", json={"channel": "telegram"})
    ).status_code == 401
    ana = await make_user(session, "ana@x.com")
    r = await client.post("/channels/link-code", json={"channel": "icq"}, headers=auth(ana))
    assert r.status_code == 422


async def test_link_code_is_rate_limited(client, session, bot):
    ana = await make_user(session, "ana@x.com")
    codes = [
        await client.post("/channels/link-code", json={"channel": "telegram"}, headers=auth(ana))
        for _ in range(6)
    ]
    assert [c.status_code for c in codes] == [200] * 5 + [429]


async def test_list_and_delete_links_are_scoped_to_user(client, session, bot):
    ana, bia = await make_user(session, "ana@x.com"), await make_user(session, "bia@x.com")
    for user, ext in ((ana, "111"), (bia, "222")):
        r = await client.post(
            "/channels/link-code", json={"channel": "telegram"}, headers=auth(user)
        )
        await link_with_code(
            session, channel="telegram", external_user_id=ext, code=r.json()["code"]
        )
    listed = (await client.get("/channels", headers=auth(ana))).json()
    assert [k["channel"] for k in listed] == ["telegram"]
    assert (await client.delete("/channels/telegram", headers=auth(ana))).status_code == 204
    left = list(await session.scalars(select(ChannelLink)))
    assert [k.user_id for k in left] == [bia.id]  # o vínculo da outra pessoa continua


async def test_delete_unknown_channel_is_rejected(client, session):
    ana = await make_user(session, "ana@x.com")
    r = await client.delete("/channels/evil%20x", headers=auth(ana))
    assert r.status_code == 422
