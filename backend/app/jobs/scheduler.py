import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_

from app.channels.ingest import purge_old_inbound
from app.core.db import SessionLocal
from app.core.redis import HEARTBEAT_KEY, redis
from app.domain.attachments import purge_orphan_attachments
from app.domain.users.models import RefreshToken

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
    async with SessionLocal() as s:
        await purge_orphan_attachments(s)


async def worker_heartbeat(ctx: dict[str, Any] | None = None) -> None:
    await redis.set(HEARTBEAT_KEY, time.time(), ex=3600)


async def purge_refresh_tokens_job(ctx: dict[str, Any] | None = None) -> None:
    """Apaga refresh expirados/revogados há >1 dia (a janela serve à detecção de reúso)."""
    now = datetime.now(UTC)
    old = now - timedelta(days=1)
    async with SessionLocal() as s:
        await s.execute(
            delete(RefreshToken).where(
                or_(RefreshToken.expires_at < now, RefreshToken.revoked_at < old)
            )
        )
        await s.commit()
