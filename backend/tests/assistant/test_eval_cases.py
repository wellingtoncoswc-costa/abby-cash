from app.assistant.intents import ParsedIntent
from tests.assistant.evalset import eval_context, load_cases, mismatches
from tests.assistant.fakes import FakeParser

ALL_INTENTS = set(ParsedIntent.model_fields["intent"].annotation.__args__)  # type: ignore[union-attr]


def test_eval_set_is_large_and_covers_every_intent():
    today, cases = load_cases()
    assert len(cases) >= 40
    assert {c["expect"]["intent"] for c in cases} == ALL_INTENTS
    texts = " ".join(c["text"] for c in cases).lower()
    for needle in (
        "ignore as regras",
        "em 1x",
        "#familia",
        "#pessoal",
        "em 3x",
        "ontem",
        "sexta",
        "mil e duzentos",
        "no pix",
        "uber",
    ):
        assert needle in texts


async def test_eval_cases():
    """O conjunto é válido e o avaliador funciona: um parser que devolve o esperado passa em
    tudo; um que erra é apontado. (Contra o modelo real: scripts/run_eval.py, fora do CI.)"""
    today, cases = load_cases()
    ctx = eval_context(today)
    category_names = {c.name for c in ctx.categories}
    for case in cases:
        expect = case["expect"]
        fields = {k: v for k, v in expect.items() if k != "category_name"}
        if "category_name" in expect:
            assert expect["category_name"] in category_names, case["text"]
            kind = "income" if expect["intent"] == "lancar_receita" else "expense"
            fields["category_index"] = 1 + next(
                i
                for i, c in enumerate(ctx.categories)
                if c.name == expect["category_name"] and c.kind == kind
            )
        want = ParsedIntent.model_validate({"confidence": 1.0, **fields})  # esperado é válido
        parser = FakeParser(want)
        got = await parser.parse(case["text"], ctx)
        assert mismatches(expect, got, ctx) == [], case["text"]
    idx = 1 + next(i for i, c in enumerate(ctx.categories) if c.name == "Mercado")
    wrong = ParsedIntent.of("lancar_despesa", amount_cents=4501, category_index=idx)
    assert mismatches({"amount_cents": 4500, "category_name": "Mercado"}, wrong, ctx) == [
        "amount_cents: esperado 4500, veio 4501"
    ]
    bad = ParsedIntent.of("lancar_receita", category_index=idx)  # índice de despesa em receita
    assert mismatches({"category_name": "Salário"}, bad, ctx) == [
        "category_name: esperado 'Salário', veio 'Outros'"
    ]
