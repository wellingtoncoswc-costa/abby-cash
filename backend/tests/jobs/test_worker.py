from app.ai.openai_parser import OpenAIIntentParser
from app.jobs.inbound import process_inbound
from app.worker import WorkerSettings


async def test_worker_registers_process_inbound_and_builds_the_parser_once():
    assert [f.__name__ for f in WorkerSettings.functions] == ["process_inbound"]
    assert WorkerSettings.functions[0] is process_inbound
    ctx: dict = {}
    await WorkerSettings.on_startup(ctx)
    assert isinstance(ctx["parser"], OpenAIIntentParser)
    assert WorkerSettings.max_tries == 1
