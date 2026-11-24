from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.channels.base import InboundMessage as Inbound
from app.channels.ingest import ingest
from app.domain.channels.models import InboundMessage


def msg() -> Inbound:
    return Inbound(
        channel="telegram", external_message_id="1:1", external_user_id="1", text="oi",
        media_kind=None, media_ref=None, received_at=datetime.now(UTC),
    )  # fmt: skip


async def test_redelivery_after_crash_reenqueues_once_per_delivery(session):
    got: list[UUID] = []

    async def crash(_: UUID) -> None:
        raise SystemExit  # morreu depois do commit, antes do enqueue

    async def ok(i: UUID) -> None:
        got.append(i)

    try:
        await ingest(session, [msg()], crash)
    except SystemExit:
        pass  # a linha continua 'received' (SystemExit não é Exception: sem rollback)
    row = await session.scalar(select(InboundMessage))
    assert row is not None
    assert await ingest(session, [msg()], ok) == 0
    assert got == [row.id]


async def test_redelivery_of_processed_row_enqueues_nothing(session):
    got: list[UUID] = []

    async def ok(i: UUID) -> None:
        got.append(i)

    await ingest(session, [msg()], ok)
    row = await session.scalar(select(InboundMessage))
    assert row is not None
    for st in ("processing", "processed"):
        row.status = st
        await session.commit()
        await ingest(session, [msg()], ok)
    assert got == [row.id]  # só a entrega original
