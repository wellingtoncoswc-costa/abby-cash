import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from starlette.requests import Request

from app.channels.base import InboundMessage
from app.channels.telegram import ChannelError, TelegramAdapter

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "telegram"


def fixture(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def adapter(handler) -> TelegramAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TelegramAdapter("T0KEN", "s3cret", client=client)


def req(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw})


def test_parse_text_update():
    msg = TelegramAdapter("T", "s").parse_update(fixture("text"))
    assert msg == InboundMessage(
        channel="telegram",
        external_message_id="111:10",  # message_id só é único dentro do chat
        external_user_id="111",
        text="gastei 45 no mercado",
        media_kind=None,
        media_ref=None,
        received_at=datetime(2026, 11, 25, 15, 0, tzinfo=UTC),
    )


def test_parse_start_voice_photo():
    a = TelegramAdapter("T", "s")
    start = a.parse_update(fixture("start_code"))
    assert start is not None and start.text == "/start 123456"
    voice = a.parse_update(fixture("voice"))
    assert voice is not None
    assert (voice.media_kind, voice.media_ref, voice.text) == ("audio", "AwACAgQAAxkBAAIB", None)
    photo = a.parse_update(fixture("photo"))
    assert photo is not None
    assert (photo.media_kind, photo.media_ref, photo.text) == ("image", "large", "farmácia 87,40")


@pytest.mark.parametrize("name", ["group", "edited", "sticker"])
def test_parse_ignores_groups_edits_and_unsupported(name):
    assert TelegramAdapter("T", "s").parse_update(fixture(name)) is None


def test_parse_ignores_bot_senders():
    update = fixture("text")
    update["message"]["from"]["is_bot"] = True
    assert TelegramAdapter("T", "s").parse_update(update) is None


async def test_parse_webhook_reads_request_body():
    body = json.dumps(fixture("text")).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request({"type": "http", "headers": []}, receive)
    msgs = await TelegramAdapter("T", "s").parse_webhook(request)
    assert [m.text for m in msgs] == ["gastei 45 no mercado"]


def test_verify_secret_header():
    a = TelegramAdapter("T", "s3cret")
    assert a.verify(req({"X-Telegram-Bot-Api-Secret-Token": "s3cret"}))
    assert not a.verify(req({"X-Telegram-Bot-Api-Secret-Token": "outro"}))
    assert not a.verify(req({}))
    assert not a.verify(req({"X-Telegram-Bot-Api-Secret-Token": "ação"}))  # não ASCII: sem 500


def test_verify_fails_closed_without_configured_secret():
    assert not TelegramAdapter("T", "").verify(req({"X-Telegram-Bot-Api-Secret-Token": ""}))


async def test_send_text_posts_to_bot_api():
    seen: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    await adapter(handler).send_text("111", "oi")
    assert str(seen[0].url) == "https://api.telegram.org/botT0KEN/sendMessage"
    assert json.loads(seen[0].content) == {"chat_id": 111, "text": "oi"}


async def test_send_error_does_not_leak_token():
    a = adapter(lambda r: httpx.Response(500, json={"ok": False}))
    with pytest.raises(ChannelError) as e:
        await a.send_text("111", "oi")
    assert "T0KEN" not in str(e.value) and "T0KEN" not in repr(e.value)


async def test_download_media_resolves_file_path_and_mime():
    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/getFile"):
            assert json.loads(r.content) == {"file_id": "AwAC"}
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "voice/f1.oga"}})
        assert r.url.path == "/file/botT0KEN/voice/f1.oga"
        return httpx.Response(200, content=b"AUDIO")

    assert await adapter(handler).download_media("AwAC") == (b"AUDIO", "audio/ogg")


async def test_bot_username_uses_env_then_get_me(monkeypatch):
    from app.core.config import get_settings

    calls = []

    def handler(r: httpx.Request) -> httpx.Response:
        calls.append(r.url.path)
        return httpx.Response(200, json={"ok": True, "result": {"username": "abby_bot"}})

    a = adapter(handler)
    monkeypatch.setattr(get_settings(), "TELEGRAM_BOT_USERNAME", "")
    assert await a.bot_username() == "abby_bot"
    assert await a.bot_username() == "abby_bot"
    assert calls == ["/botT0KEN/getMe"]  # cache: uma chamada só
    monkeypatch.setattr(get_settings(), "TELEGRAM_BOT_USERNAME", "do_env")
    assert await adapter(handler).bot_username() == "do_env"


async def test_set_and_delete_webhook_payloads():
    seen = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append((r.url.path.rsplit("/", 1)[1], json.loads(r.content)))
        return httpx.Response(200, json={"ok": True, "result": True})

    a = adapter(handler)
    await a.set_webhook("https://x.com/webhooks/telegram")
    await a.delete_webhook()
    assert seen == [
        (
            "setWebhook",
            {
                "url": "https://x.com/webhooks/telegram",
                "secret_token": "s3cret",
                "allowed_updates": ["message"],
            },
        ),
        ("deleteWebhook", {}),
    ]
