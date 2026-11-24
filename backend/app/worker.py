from typing import Any

from arq.connections import RedisSettings

from app.ai.openai_parser import OpenAIIntentParser
from app.core.config import get_settings
from app.jobs.inbound import process_inbound


async def startup(ctx: dict[str, Any]) -> None:
    ctx["parser"] = OpenAIIntentParser()  # um cliente por processo do worker


class WorkerSettings:
    functions = [process_inbound]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().REDIS_URL)
    max_tries = 1  # ponytail: sem retry; uma mensagem presa em "processing" exige reenvio manual
