import json
from uuid import UUID

import httpx
from sqlalchemy import select

from app.channels.poll import poll_once
from app.channels.telegram import TelegramAdapter
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
    assert len(enqueued) == 2
    await poll_once(adapter, offset, enqueue)  # mesma entrega de novo: nada duplica
    assert len(enqueued) == 2
