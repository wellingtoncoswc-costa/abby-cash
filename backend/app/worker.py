from typing import Any

from arq.connections import RedisSettings

from app.core.config import get_settings


async def noop(ctx: dict[str, Any]) -> None:  # ponytail: placeholder até o M3 trazer jobs reais
    return None


class WorkerSettings:
    functions = [noop]
    redis_settings = RedisSettings.from_dsn(get_settings().REDIS_URL)
