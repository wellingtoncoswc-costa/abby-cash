from redis.asyncio import Redis

from app.core.config import get_settings

redis = Redis.from_url(get_settings().REDIS_URL, decode_responses=True)

HEARTBEAT_KEY = "worker:heartbeat"

_INCR_TTL = """
local n = redis.call('INCR', KEYS[1])
if redis.call('TTL', KEYS[1]) < 0 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return n
"""


async def incr_ttl(key: str, ttl_s: int) -> int:
    """INCR + TTL numa só operação atômica: a chave nunca existe sem expiração."""
    return int(await redis.eval(_INCR_TTL, 1, key, ttl_s))
