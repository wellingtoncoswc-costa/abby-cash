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
            next_offset = update["update_id"] + 1
        except (KeyError, TypeError):
            log.warning("telegram poll: update without update_id")
            continue  # ponytail: sem update_id não há como avançar; o próximo update avança
        try:
            if (msg := adapter.parse_update(update)) is not None:
                async with SessionLocal() as session:
                    await ingest(session, [msg], enqueue)
        except Exception as e:
            # update venenoso (formato ou erro determinístico): pula, senão trava/gira em loop.
            # ponytail: erro transitório também descarta o update; o usuário reenvia. Só o tipo no
            # log (a mensagem pode ter texto do usuário).
            log.warning("telegram poll: skipping update (%s)", type(e).__name__)
        offset = next_offset  # avança sempre, mesmo após falha
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
