import asyncio
import json
import logging
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.api import webhooks
from app.channels import registry
from app.channels.telegram import TelegramAdapter
from app.core.redis import redis
from app.domain.channels.models import InboundMessage
from app.jobs.queue import enqueue_inbound

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "telegram"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "s3cret"}


def update(name: str = "text") -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def tg(monkeypatch):
    monkeypatch.setitem(registry._adapters, "telegram", TelegramAdapter("T0KEN", "s3cret"))


@pytest.fixture
def enqueued(monkeypatch) -> list[UUID]:
    got: list[UUID] = []

    async def fake(inbound_id: UUID) -> None:
        got.append(inbound_id)

    monkeypatch.setattr(webhooks, "enqueue_inbound", fake)
    return got


async def post(client, name: str = "text"):
    return await client.post("/webhooks/telegram", json=update(name), headers=HEADERS)


async def count(session) -> int:
    return await session.scalar(select(func.count()).select_from(InboundMessage))


async def test_telegram_webhook_rejects_bad_secret(client, session, enqueued):
    r = await client.post("/webhooks/telegram", json=update())
    assert r.status_code == 401
    r = await client.post(
        "/webhooks/telegram", json=update(), headers={"X-Telegram-Bot-Api-Secret-Token": "errado"}
    )
    assert r.status_code == 401
    assert await count(session) == 0 and enqueued == []


async def test_webhook_enqueues_and_returns_200(client, session, enqueued):
    r = await post(client)
    assert r.status_code == 200 and r.json() == {"ok": True}
    row = await session.scalar(select(InboundMessage))
    assert row is not None
    assert (row.channel, row.external_message_id, row.external_user_id) == (
        "telegram", "111:10", "111",
    )  # fmt: skip
    assert (row.text, row.status, row.user_id) == ("gastei 45 no mercado", "received", None)
    assert enqueued == [row.id]


async def test_webhook_ignores_unsupported_updates_with_200(client, session, enqueued):
    for name in ("group", "edited", "sticker"):
        assert (await post(client, name)).status_code == 200
    assert await count(session) == 0 and enqueued == []


async def test_webhook_unknown_channel_and_bad_payload(client, enqueued):
    r = await client.post("/webhooks/nope", json=update(), headers=HEADERS)
    assert r.status_code == 404
    r = await client.post("/webhooks/telegram", content=b"not json", headers=HEADERS)
    assert r.status_code == 400


async def test_duplicate_webhook_ingested_once(client, session, enqueued):
    for _ in range(3):  # reenvios do Telegram
        assert (
            await client.post("/webhooks/telegram", json=update(), headers=HEADERS)
        ).status_code == 200
    await asyncio.gather(
        *[
            client.post("/webhooks/telegram", json=update("voice"), headers=HEADERS)
            for _ in range(5)
        ]
    )  # entregas simultâneas
    assert await count(session) == 2
    assert len(set(enqueued)) == 2  # 'received' reenfileira; o ARQ dedupe pelo _job_id


async def test_enqueue_failure_rolls_back_row_so_retry_works(client, session, monkeypatch):
    async def boom(_: UUID) -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr(webhooks, "enqueue_inbound", boom)
    with pytest.raises(RuntimeError):
        await post(client)
    assert await count(session) == 0  # sem linha órfã: o reenvio do Telegram entra de novo
    got: list[UUID] = []

    async def ok(inbound_id: UUID) -> None:
        got.append(inbound_id)

    monkeypatch.setattr(webhooks, "enqueue_inbound", ok)
    await post(client)
    assert await count(session) == 1 and len(got) == 1


async def test_enqueue_inbound_uses_arq_queue_with_dedupe():
    iid = uuid4()
    await enqueue_inbound(iid)
    await enqueue_inbound(iid)  # mesmo job_id: o ARQ não duplica
    assert await redis.zcard("arq:queue") == 1


async def test_token_never_leaks_in_logs_or_responses(client, enqueued, caplog):
    caplog.set_level(logging.DEBUG)
    r = await post(client)
    r2 = await client.post("/webhooks/telegram", json=update(), headers={})
    assert "T0KEN" not in r.text + r2.text + caplog.text


async def test_malformed_updates_return_400_without_echo(client, enqueued):
    for body in ([1, 2], "str", {"message": {"chat": {"type": "private"}, "text": "x"}}):
        r = await client.post("/webhooks/telegram", json=body, headers=HEADERS)
        assert r.status_code == 400 and "T0KEN" not in r.text and "s3cret" not in r.text
    assert enqueued == []


async def test_oversized_body_returns_413(client, enqueued):
    r = await client.post("/webhooks/telegram", content=b"x" * 1_000_001, headers=HEADERS)
    assert r.status_code == 413
    r = await client.post(
        "/webhooks/telegram", content=b"{}", headers={**HEADERS, "Content-Length": "2000000"}
    )  # header declarado grande (o httpx pode sobrescrever; o corpo real é checado também)
    assert r.status_code == 413


async def test_non_numeric_content_length_is_400_not_500(client, enqueued):
    r = await client.post(
        "/webhooks/telegram", content=b"{}", headers={**HEADERS, "Content-Length": "abc"}
    )
    assert r.status_code == 400
