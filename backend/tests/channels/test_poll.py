import asyncio
import json
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from app.channels import poll
from app.channels.poll import poll_once
from app.channels.telegram import ChannelError, TelegramAdapter
from app.domain.channels.models import InboundMessage
from tests.channels.test_telegram import fixture


async def test_poll_once_ingests_updates_and_advances_offset(session):
    sent_bodies = []

    def handler(r: httpx.Request) -> httpx.Response:
        sent_bodies.append(json.loads(r.content))
        updates = [fixture("text"), fixture("group"), fixture("voice")]
        return httpx.Response(200, json={"ok": True, "result": updates})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TelegramAdapter("T0KEN", "s3cret", client=client)
    enqueued: list[UUID] = []

    async def enqueue(inbound_id: UUID) -> None:
        enqueued.append(inbound_id)

    offset = await poll_once(adapter, 5, enqueue)
    assert sent_bodies[0]["offset"] == 5 and sent_bodies[0]["timeout"] == 30
    assert offset == 900004  # último update_id (900003) + 1, mesmo o ignorado (grupo)
    rows = list(await session.scalars(select(InboundMessage).order_by(InboundMessage.created_at)))
    assert [r.external_message_id for r in rows] == ["111:10", "111:12"]
    assert len(set(enqueued)) == 2  # 'received' reenfileira; o ARQ dedupe
    await poll_once(adapter, offset, enqueue)  # mesma entrega de novo: nada duplica
    assert len(set(enqueued)) == 2  # 'received' reenfileira; o ARQ dedupe


def fake_adapter(updates: list) -> TelegramAdapter:
    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": updates})

    return TelegramAdapter(
        "T0KEN", "s", client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


async def test_poison_update_is_skipped_and_offset_still_advances(session):
    poison = {"update_id": 7, "message": {"chat": {"type": "private", "id": 1}, "text": "x"}}
    good = fixture("text")
    adapter = fake_adapter([poison, "lixo", good])
    got: list[UUID] = []

    async def enqueue(i: UUID) -> None:
        got.append(i)

    offset = await poll_once(adapter, None, enqueue)
    assert offset == good["update_id"] + 1 and len(got) == 1


async def test_bad_response_shape_is_channel_error():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": False}))
    )
    with pytest.raises(ChannelError):
        await TelegramAdapter("T0KEN", "s", client=client).get_updates(None)


async def test_poll_forever_survives_errors_with_backoff_and_no_token(monkeypatch, caplog):
    calls = iter([RuntimeError("redis T0KEN down"), RuntimeError("x"), RuntimeError("y"), 42])
    seen_offsets: list = []

    async def fake_once(adapter, offset, enqueue):
        seen_offsets.append(offset)
        c = next(calls)
        if isinstance(c, Exception):
            raise c
        return c

    slept: list[float] = []

    async def sleep(d: float) -> None:
        slept.append(d)
        if len(seen_offsets) == 5:
            raise asyncio.CancelledError  # encerra o loop no teste

    monkeypatch.setattr(poll, "poll_once", fake_once)
    with pytest.raises(asyncio.CancelledError):
        await poll.poll_forever(fake_adapter([]), sleep=sleep)
    assert slept[:3] == [1, 2, 4] and seen_offsets[:4] == [None] * 4 and seen_offsets[4] == 42
    assert "T0KEN" not in caplog.text and "RuntimeError" in caplog.text


async def test_malformed_last_update_still_advances_offset_past_it(session):
    good = fixture("text")
    bad = {"update_id": good["update_id"] + 5, "message": "lixo"}
    got: list[UUID] = []

    async def enqueue(i: UUID) -> None:
        got.append(i)

    offset = await poll_once(fake_adapter([good, bad]), None, enqueue)
    assert offset == bad["update_id"] + 1 and len(got) == 1


async def test_ingest_failure_skips_that_update_and_advances(session, monkeypatch, caplog):
    first, second = fixture("text"), dict(fixture("text"))
    second["update_id"] = first["update_id"] + 1
    second["message"] = {**first["message"], "message_id": 99}
    calls = 0

    async def boom(session, msgs, enqueue):
        nonlocal calls
        calls += 1
        raise RuntimeError("secret user text")

    monkeypatch.setattr(poll, "ingest", boom)

    async def enqueue(i: UUID) -> None: ...

    offset = await poll_once(fake_adapter([first, second]), None, enqueue)
    assert calls == 2 and offset == second["update_id"] + 1
    assert "secret user text" not in caplog.text and "RuntimeError" in caplog.text
