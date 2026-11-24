from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.ai.openai_parser import OpenAIIntentParser
from app.core.config import get_settings
from app.jobs.budgets import check_budget_thresholds
from app.jobs.digest import send_weekly_digests
from app.jobs.goals import notify_goals_behind
from app.jobs.health import check_evolution_connection
from app.jobs.inbound import process_inbound


async def startup(ctx: dict[str, Any]) -> None:
    ctx["parser"] = OpenAIIntentParser()  # um cliente por processo do worker


class WorkerSettings:
    functions = [process_inbound]
    cron_jobs = [
        cron(check_evolution_connection, minute=set(range(0, 60, 5))),
        cron(check_budget_thresholds, hour=11, minute=0),
        cron(notify_goals_behind, hour=12, minute=0),  # 09:00 em São Paulo; age só no dia 1
        cron(send_weekly_digests, minute=0),  # toda hora; filtra domingo 20h por usuário
    ]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().REDIS_URL)
    max_tries = 1  # ponytail: sem retry; uma mensagem presa em "processing" exige reenvio manual
