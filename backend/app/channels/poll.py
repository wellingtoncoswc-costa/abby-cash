import asyncio
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.channels.ingest import ingest
from app.channels.telegram import ChannelError, TelegramAdapter
from app.core.db import SessionLocal
from app.jobs.queue import enqueue_inbound

log = logging.getLogger(__name__)


async def poll_once(
    adapter: TelegramAdapter, offset: int | None, enqueue: Callable[[UUID], Awaitable[None]]
) -> int | None:
    """Um getUpdates: manda cada mensagem pela MESMA porta do webhook (`ingest`)."""
    for update in await adapter.get_updates(offset):
        msg = adapter.parse_update(update)
        if msg is not None:
            async with SessionLocal() as session:
                await ingest(session, [msg], enqueue)
        offset = update["update_id"] + 1  # só avança depois de gravar/enfileirar
    return offset


async def poll_forever(adapter: TelegramAdapter) -> None:
    """Long polling para dev sem HTTPS público. O worker (`arq`) precisa estar rodando."""
    offset: int | None = None
    while True:
        try:
            offset = await poll_once(adapter, offset, enqueue_inbound)
        except ChannelError as e:
            log.warning("telegram poll failed: %s", e)
            await asyncio.sleep(3)
