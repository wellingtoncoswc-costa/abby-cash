from uuid import UUID

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings

_pool: ArqRedis | None = None


async def enqueue_inbound(inbound_id: UUID) -> None:
    """Enfileira `process_inbound`. `_job_id` = id da mensagem: o ARQ ignora o duplicado."""
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().REDIS_URL))
    await _pool.enqueue_job("process_inbound", str(inbound_id), _job_id=str(inbound_id))
