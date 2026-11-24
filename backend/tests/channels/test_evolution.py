import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from starlette.requests import Request

from app.channels.evolution import EvolutionAdapter, EvolutionClient
from app.channels.telegram import ChannelError

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "evolution"


def fixture(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def req(headers: dict[str, str] | None = None, query: str = "") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "headers": raw, "query_string": query.encode()})


def adapter(handler=None, secret: str = "s3cret") -> EvolutionAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler or (lambda r: None)))
    return EvolutionAdapter(EvolutionClient("http://evo:8080", "K3Y", "abby", client), secret)


def test_parses_text_audio_image():
    a = adapter()
    t = a.parse_event(fixture("text"))
    assert t is not None
    assert (t.channel, t.external_message_id, t.external_user_id, t.text) == (
        "whatsapp_evolution", "3EB0A1", "5511988887777", "gastei 45 no mercado",
    )  # fmt: skip
    assert t.received_at == datetime.fromtimestamp(1764082800, UTC)
    assert a.parse_event(fixture("extended")).text == "123456"
    au = a.parse_event(fixture("audio"))
    assert (au.media_kind, au.media_ref, au.text) == ("audio", "3EB0A3", None)
    im = a.parse_event(fixture("image"))
    assert (im.media_kind, im.media_ref, im.text) == ("image", "3EB0A4", "farmácia 87,40")


@pytest.mark.parametrize("name", ["group", "from_me", "status", "lid", "sticker", "other_event"])
def test_ignores_group_and_from_me(name):
    assert adapter().parse_event(fixture(name)) is None


@pytest.mark.parametrize(
    "bad",
    [
        [],
        "x",
        {"event": "messages.upsert", "data": []},
        {"event": "messages.upsert", "data": {"key": 1}},
    ],
)
def test_malformed_is_value_error(bad):
    with pytest.raises(ValueError):
        adapter().parse_event(bad)


async def test_parse_webhook_bad_json_is_value_error():
    r = Request({"type": "http", "headers": [], "query_string": b""})
    r._body = b"{nope"
    with pytest.raises(ValueError):
        await adapter().parse_webhook(r)


def test_verify_header_only_and_fail_closed():
    a = adapter()
    assert a.verify(req({"x-webhook-secret": "s3cret"}))
    assert not a.verify(req(query="token=s3cret"))
    assert not a.verify(req({"x-webhook-secret": "nope"}))
    assert not a.verify(req())
    assert not a.verify(req({"x-webhook-secret": "é"}))
    assert not adapter(secret="").verify(req({"x-webhook-secret": ""}))


async def test_send_text_and_state_use_apikey_header():
    seen: list[httpx.Request] = []

    def h(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        if "connectionState" in r.url.path:
            return httpx.Response(200, json={"instance": {"instanceName": "abby", "state": "open"}})
        return httpx.Response(201, json={})

    a = adapter(h)
    await a.send_text("5511988887777", "oi")
    assert await a.client.connection_state() == "open"
    assert seen[0].url.path == "/message/sendText/abby"
    assert json.loads(seen[0].content) == {"number": "5511988887777", "text": "oi"}
    assert seen[0].headers["apikey"] == "K3Y" and "K3Y" not in str(seen[0].url)


async def test_errors_never_leak_key_or_url():
    def h(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom http://evo:8080 K3Y")

    with pytest.raises(ChannelError) as e:
        await adapter(h).send_text("55", "oi")
    assert "K3Y" not in str(e.value) and "evo:8080" not in str(e.value)
    with pytest.raises(ChannelError):
        await adapter(lambda r: httpx.Response(500)).client.connection_state()


async def test_set_webhook_payload_and_download():
    seen: list[httpx.Request] = []

    def h(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        return httpx.Response(200, json={"base64": "aGk=", "mimetype": "audio/ogg; codecs=opus"})

    a = adapter(h)
    await a.client.set_webhook("https://x/webhooks/whatsapp_evolution", "s3cret")
    body = json.loads(seen[0].content)["webhook"]
    assert body["events"] == ["MESSAGES_UPSERT"] and body["enabled"] is True
    assert body["headers"] == {"x-webhook-secret": "s3cret"}
    assert await a.download_media("3EB0A3", 10**6) == (b"hi", "audio/ogg")


def _with(msg: dict, **key) -> dict:
    ev = fixture("text")
    ev["data"]["message"] = msg
    ev["data"]["key"].update(key)
    return ev


def test_lid_uses_real_number_alternates():
    a = adapter()
    for alt in (
        {"remoteJidAlt": "5511977776666@s.whatsapp.net"},
        {"senderPn": "5511977776666@s.whatsapp.net"},
    ):
        m = a.parse_event(_with({"conversation": "oi"}, remoteJid="1234@lid", **alt))
        assert m is not None and m.external_user_id == "5511977776666"
    assert a.parse_event(_with({"conversation": "oi"}, remoteJid="1234@lid")) is None


def test_unwraps_ephemeral_viewonce_document():
    a = adapter()
    eph = {"ephemeralMessage": {"message": {"extendedTextMessage": {"text": "gastei 9"}}}}
    assert a.parse_event(_with(eph)).text == "gastei 9"
    vo = {"viewOnceMessage": {"message": {"imageMessage": {"caption": "nota 5"}}}}
    m = a.parse_event(_with(vo))
    assert (m.media_kind, m.text) == ("image", "nota 5")
    aud = {
        "ephemeralMessage": {"message": {"viewOnceMessageV2": {"message": {"audioMessage": {}}}}}
    }
    assert a.parse_event(_with(aud)).media_kind == "audio"
    doc = {"documentWithCaptionMessage": {"message": {"extendedTextMessage": {"text": "oi"}}}}
    assert a.parse_event(_with(doc)).text == "oi"


def test_unsupported_logs_type_only(caplog):
    caplog.set_level("INFO")
    ev = _with({"contactMessage": {"displayName": "SECRETNAME"}})
    ev["data"]["messageType"] = "contactMessage"
    assert adapter().parse_event(ev) is None
    assert "type=contactMessage" in caplog.text
    assert "SECRETNAME" not in caplog.text and "5511988887777" not in caplog.text
