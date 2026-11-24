import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.channels.ingest import purge_old_inbound
from app.core.db import SessionLocal

log = logging.getLogger(__name__)


async def isolated(label: str, fn: Callable[[], Awaitable[Any]]) -> None:
    """Uma falha (de um usuário/fatura) não derruba as demais; o log só leva o tipo da exceção."""
    try:
        await fn()
    except Exception as e:
        log.warning("job %s failed for one item (%s)", label, type(e).__name__)


async def purge_inbound_job(ctx: dict[str, Any] | None = None) -> None:
    async with SessionLocal() as s:
        await purge_old_inbound(s)
