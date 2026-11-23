"""Conjunto de avaliação do interpretador: carga, contexto fixo e comparação de resultados."""

from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from app.assistant.context import (
    CtxAccount,
    CtxCard,
    CtxCategory,
    CtxGoal,
    SpaceContext,
)
from app.assistant.intents import ParsedIntent
from app.core.text import fold
from app.domain.categories.defaults import DEFAULT_EXPENSE, DEFAULT_INCOME

EVAL_PATH = Path(__file__).with_name("eval_cases.yaml")
_FUZZY = {"category_name", "account_hint", "card_hint", "goal_hint"}


def load_cases() -> tuple[date, list[dict[str, Any]]]:
    data = yaml.safe_load(EVAL_PATH.read_text(encoding="utf-8"))
    return date.fromisoformat(data["today"]), data["cases"]


def eval_context(today: date) -> SpaceContext:
    space = uuid4()
    return SpaceContext(
        space_id=space,
        space_name="Pessoal",
        categories=[CtxCategory(uuid4(), n, "expense") for n in DEFAULT_EXPENSE]
        + [CtxCategory(uuid4(), n, "income") for n in DEFAULT_INCOME],
        accounts=[
            CtxAccount(uuid4(), "Carteira", "wallet", space),
            CtxAccount(uuid4(), "Nubank", "checking", space),
            CtxAccount(uuid4(), "Itaú", "checking", space),
        ],
        cards=[CtxCard(uuid4(), "Nubank", space), CtxCard(uuid4(), "Visa", space)],
        goals=[CtxGoal(uuid4(), "Viagem"), CtxGoal(uuid4(), "Carro")],
        rules=[("padaria pao quente", "Alimentação")],
        default_account_id=None,
        today=today,
        tz="America/Sao_Paulo",
    )


def mismatches(expect: dict[str, Any], got: ParsedIntent) -> list[str]:
    """Campos esperados que o resultado não cumpre. Texto livre compara sem acento/caixa."""
    out = []
    for key, want in expect.items():
        have = getattr(got, key)
        if key == "occurred_on":
            want = date.fromisoformat(str(want))
        if key == "category_name":
            ok = fold(str(have or "")) == fold(str(want))
        elif key in _FUZZY:
            ok = fold(str(want)) in fold(str(have or ""))
        else:
            ok = have == want
        if not ok:
            out.append(f"{key}: esperado {want!r}, veio {have!r}")
    return out
