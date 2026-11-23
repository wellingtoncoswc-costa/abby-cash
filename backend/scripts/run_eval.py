"""Roda o conjunto de avaliação contra o modelo REAL (usa OPENAI_API_KEY e custa tokens).

Manual, nunca no CI:  cd backend && uv run python scripts/run_eval.py [--min 0.9]
Sai com código 1 se a taxa de acerto ficar abaixo de --min.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # para importar `app` e `tests`

import app.ai.openai_parser as openai_parser  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from tests.assistant.evalset import eval_context, load_cases, mismatches  # noqa: E402


async def _no_usage(*_: Any, **__: Any) -> None:  # o contexto de avaliação não tem espaço no banco
    return None


async def main(minimum: float) -> int:
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY ausente no .env")
    openai_parser.record_ai_usage = _no_usage  # type: ignore[assignment]
    today, cases = load_cases()
    ctx = eval_context(today)
    parser = openai_parser.OpenAIIntentParser()
    print(f"modelo: {parser.model} · {len(cases)} casos · hoje = {today}")
    ok = 0
    for case in cases:
        try:
            diff = mismatches(case["expect"], await parser.parse(case["text"], ctx), ctx)
        except Exception as e:  # noqa: BLE001 - qualquer falha da API conta como erro do caso
            diff = [f"erro: {type(e).__name__}"]
        ok += not diff
        print(("OK   " if not diff else "FALHA"), case["text"], *(f"\n       - {d}" for d in diff))
    rate = ok / len(cases)
    print(f"\nacertos: {ok}/{len(cases)} ({rate:.0%})")
    return 0 if rate >= minimum else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=float, default=0.9, help="taxa mínima de acerto (0 a 1)")
    raise SystemExit(asyncio.run(main(ap.parse_args().min)))
