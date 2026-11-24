from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.ai.openai_parser import OpenAIIntentParser
from app.ai.receipt import OpenAIReceiptReader
from app.ai.stt import HttpWhisperTranscriber
from app.core.config import get_settings
from app.jobs.bills import daily_bills_job, send_bill_reminders
from app.jobs.budgets import check_budget_thresholds
from app.jobs.digest import send_weekly_digests
from app.jobs.goals import notify_goals_behind
from app.jobs.health import check_evolution_connection
from app.jobs.inbound import process_inbound
from app.jobs.pockets import sync_cdi_job
from app.jobs.scheduler import purge_inbound_job, purge_refresh_tokens_job, worker_heartbeat


async def startup(ctx: dict[str, Any]) -> None:
    ctx["parser"] = OpenAIIntentParser()  # um cliente por processo do worker
    ctx["receipt_reader"] = OpenAIReceiptReader()
    ctx["transcriber"] = HttpWhisperTranscriber()


class WorkerSettings:
    functions = [process_inbound]
    cron_jobs = [
        cron(worker_heartbeat, second={0, 30}, run_at_startup=True),
        cron(check_evolution_connection, minute=set(range(0, 60, 5))),
        cron(send_bill_reminders, minute={0, 15, 30, 45}),
        cron(daily_bills_job, hour=6, minute=10),
        cron(sync_cdi_job, hour=set(range(11, 24)), minute=30),  # 08:30 em SP, de hora em hora
        cron(purge_inbound_job, hour=7, minute=30),
        cron(purge_refresh_tokens_job, hour=7, minute=35),
        cron(check_budget_thresholds, hour=11, minute=0),
        cron(notify_goals_behind, hour=12, minute=0),  # 09:00 em São Paulo; age só no dia 1
        cron(send_weekly_digests, minute=0),  # toda hora; filtra domingo 20h por usuário
    ]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().REDIS_URL)
    max_tries = 1  # ponytail: sem retry; uma mensagem presa em "processing" exige reenvio manual
