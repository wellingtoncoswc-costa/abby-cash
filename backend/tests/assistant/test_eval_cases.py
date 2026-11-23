from app.assistant.intents import ParsedIntent
from tests.assistant.evalset import eval_context, load_cases, mismatches
from tests.assistant.fakes import FakeParser

ALL_INTENTS = set(ParsedIntent.model_fields["intent"].annotation.__args__)  # type: ignore[union-attr]


def test_eval_set_is_large_and_covers_every_intent():
    today, cases = load_cases()
    assert len(cases) >= 40
    assert {c["expect"]["intent"] for c in cases} == ALL_INTENTS
    texts = " ".join(c["text"] for c in cases).lower()
    for needle in ("#pessoal", "em 3x", "ontem", "sexta", "mil e duzentos", "no pix", "uber"):
        assert needle in texts


async def test_eval_cases():
    """O conjunto é válido e o avaliador funciona: um parser que devolve o esperado passa em
    tudo; um que erra é apontado. (Contra o modelo real: scripts/run_eval.py, fora do CI.)"""
    today, cases = load_cases()
    ctx = eval_context(today)
    category_names = {c.name for c in ctx.categories}
    for case in cases:
        expect = case["expect"]
        if "category_name" in expect:
            assert expect["category_name"] in category_names, case["text"]
        want = ParsedIntent.model_validate({"confidence": 1.0, **expect})  # esperado é válido
        parser = FakeParser(want)
        got = await parser.parse(case["text"], ctx)
        assert mismatches(expect, got) == [], case["text"]
    wrong = ParsedIntent.of("lancar_despesa", amount_cents=4501, category_name="mercado")
    assert mismatches({"amount_cents": 4500, "category_name": "Mercado"}, wrong) == [
        "amount_cents: esperado 4500, veio 4501"
    ]
