import asyncio
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.channels.ingest import ingest
from app.channels.telegram import TelegramAdapter
from app.core.db import SessionLocal
from app.jobs.queue import enqueue_inbound

log = logging.getLogger(__name__)


async def poll_once(
    adapter: TelegramAdapter, offset: int | None, enqueue: Callable[[UUID], Awaitable[None]]
) -> int | None:
    """Um getUpdates: manda cada mensagem pela MESMA porta do webhook (`ingest`)."""
    for update in await adapter.get_updates(offset):
        try:
            msg = adapter.parse_update(update)
            next_offset = update["update_id"] + 1
        except (ValueError, KeyError, TypeError):
            log.warning("telegram poll: skipping malformed update")  # sem conteúdo: pode ter dados
            continue  # ponytail: update sem update_id não avança o offset; o próximo avança
        if msg is not None:
            async with SessionLocal() as session:
                await ingest(session, [msg], enqueue)
        offset = next_offset  # só avança depois de gravar/enfileirar
    return offset


async def poll_forever(
    adapter: TelegramAdapter, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
) -> None:
    """Long polling para dev sem HTTPS público. O worker (`arq`) precisa estar rodando.

    Sobrevive a qualquer erro (Redis, banco, rede) com backoff 1,2,4..30 s."""
    offset: int | None = None
    delay = 1.0
    while True:
        try:
            offset = await poll_once(adapter, offset, enqueue_inbound)
            delay = 1.0
        except Exception as e:
            # só a classe: a mensagem/traceback de erros httpx pode conter a URL com o token
            log.error("telegram poll failed (%s); retrying in %.0fs", type(e).__name__, delay)
            await sleep(delay)
            delay = min(delay * 2, 30.0)
