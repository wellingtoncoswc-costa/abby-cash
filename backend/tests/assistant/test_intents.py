from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.assistant.context import CtxCategory, SpaceContext
from app.assistant.intents import ParsedIntent
from app.assistant.resolve import pick_category, resolve_hint
from app.core.text import fold


def mk(**kw):
    return ParsedIntent.model_validate({"intent": "lancar_despesa", "confidence": 1.0, **kw})


@pytest.mark.parametrize(
    "kw",
    [
        {"amount_cents": 0}, {"amount_cents": -1}, {"amount_cents": 10**10 + 1},
        {"installments": 0}, {"installments": -2}, {"installments": 73},
        {"confidence": -0.1}, {"confidence": 1.1}, {"confidence": float("nan")},
        {"choice": 0}, {"choice": 100},
    ],
)  # fmt: skip
def test_out_of_range_is_rejected(kw):
    with pytest.raises(ValidationError):
        mk(**kw)


@pytest.mark.parametrize(
    "kw",
    [{"amount_cents": 1}, {"amount_cents": 10**10}, {"installments": 1}, {"installments": 2},
     {"installments": 72}, {"confidence": 0}, {"choice": 1}, {"choice": 99}],
)  # fmt: skip
def test_bounds_are_inclusive(kw):
    mk(**kw)


def test_free_text_is_stripped_of_control_chars_and_truncated():
    p = mk(description="a\x00b\nc\x7fd" + "x" * 300, merchant="m" * 300, account_hint="n" * 300,
           card_hint="c\x01d", goal_hint="g\ne")  # fmt: skip
    assert (
        p.description is not None and p.description.startswith("abcd") and len(p.description) == 200
    )
    assert p.merchant == "m" * 200 and p.account_hint == "n" * 100
    assert (p.card_hint, p.goal_hint) == ("cd", "ge")


def test_json_schema_has_no_constraints_the_strict_mode_rejects():
    props = ParsedIntent.model_json_schema()["properties"]
    assert not any({"minimum", "maximum", "maxLength"} & set(v) for v in props.values())


def test_fold_drops_control_chars():
    assert fold("Alimenta\x7fo\x00 Sa\x01úde") == "alimentao saude"


def _ctx():
    cats = [CtxCategory(uuid4(), "Mercado", "expense"), CtxCategory(uuid4(), "Salário", "income")]
    return SpaceContext(uuid4(), "x", cats, [], [], [], [], None, date(2026, 11, 25), "UTC")


def test_pick_category():
    ctx = _ctx()
    assert pick_category(ctx, "expense", 1) == ctx.categories[0]
    assert pick_category(ctx, "income", 2) == ctx.categories[1]
    assert pick_category(ctx, "expense", 2) is None  # tipo errado
    assert pick_category(ctx, "expense", 0) is None and pick_category(ctx, "expense", 3) is None
    assert pick_category(ctx, "expense", None) is None


def test_resolve_hint_is_accent_case_and_typo_tolerant():
    names = ["Nubank", "Itaú", "Carteira"]
    assert resolve_hint("itau", names) == "Itaú"
    assert resolve_hint("NUBANC", names) == "Nubank"
    assert resolve_hint("xpto", names) is None and resolve_hint(None, names) is None
