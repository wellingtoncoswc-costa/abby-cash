from arq.connections import RedisSettings

from app.core.config import get_settings
from app.jobs.inbound import process_inbound


class WorkerSettings:
    functions = [process_inbound]
    redis_settings = RedisSettings.from_dsn(get_settings().REDIS_URL)
    max_tries = 1  # ponytail: sem retry; uma mensagem presa em "processing" exige reenvio manual
