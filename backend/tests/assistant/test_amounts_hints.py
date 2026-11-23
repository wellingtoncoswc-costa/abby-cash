from datetime import date

import pytest

from app.assistant.amounts import extract_amount, parse_amount_words, parse_bare_amount
from app.assistant.hints import extract_hints, resolve_date
from tests.assistant.evalset import load_cases

TODAY = date(2026, 11, 25)  # quarta-feira


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("mil e duzentos", 120_000), ("quarenta e cinco", 4_500), ("dois mil", 200_000),
        ("cento e vinte reais", 12_000), ("tres mil e quinhentos", 350_000), ("cem", 10_000),
        ("quarenta e cinco reais e cinquenta centavos", 4_550), ("vinte contos", 2_000),
        ("dois mil e trezentos e cinquenta", 235_000), ("um real", 100),
        ("comprei uma pizza de quarenta", 4_000), ("nada de valor aqui", None), ("zero", None),
    ],
)  # fmt: skip
def test_parse_amount_words(text, cents):
    assert parse_amount_words(text) == cents


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("gastei 45 no mercado", 4_500), ("R$ 1.234,56", 123_456), ("1234.56", 123_456),
        ("R$45", 4_500), ("45 reais", 4_500), ("45,5", 4_550), ("2 mil", 200_000),
        ("2,5 mil", 250_000), ("gastei mil e duzentos", 120_000), ("gastei 30 dia 15", 3_000),
        ("mercado em 3x 90", 9_000), ("25 de dezembro gastei 10", 1_000),
        ("#pessoal pizza 50", 5_000), ("uber 23/11 18", 1_800),
        ("gastei 0", None), ("sem valor", None),
    ],
)  # fmt: skip
def test_extract_amount_formats(text, cents):
    assert extract_amount(text) == cents


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("45", 4_500), ("R$ 45,50", 4_550), ("quarenta e cinco reais", 4_500),
        ("mil e duzentos", 120_000), ("gastei 30 uber", None), ("30 uber", None), ("0", None),
        ("-10", None), ("saldo", None),
    ],
)  # fmt: skip
def test_parse_bare_amount_only_accepts_a_lone_value(text, cents):
    assert parse_bare_amount(text) == cents


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("ifood 67 ontem", date(2026, 11, 24)), ("anteontem 30", date(2026, 11, 23)),
        ("hoje 10", date(2026, 11, 25)), ("sexta 50", date(2026, 11, 20)),
        ("quarta 20", date(2026, 11, 18)), ("segunda-feira 10", date(2026, 11, 23)),
        ("sábado fui", date(2026, 11, 21)), ("dia 15 luz", date(2026, 11, 15)),
        ("dia 28 luz", date(2026, 10, 28)), ("23/11 uber", date(2026, 11, 23)),
        ("5 de outubro", date(2026, 10, 5)), ("dia 25 de dezembro", date(2025, 12, 25)),
        ("1 de março", date(2026, 3, 1)), ("31/12 x", date(2025, 12, 31)),
        ("1/2/25 x", date(2025, 2, 1)), ("sem data", None),
    ],
)  # fmt: skip
def test_resolve_date(text, want):
    assert resolve_date(text, TODAY) == want


def test_hints_installments_tags_and_total():
    h = extract_hints("tv 3x de 500", TODAY)
    assert (h.installments, h.amount_cents) == (3, 150_000)  # 3x de 500 = total 1.500
    h = extract_hints("tv 600 em 3x", TODAY)
    assert (h.installments, h.amount_cents) == (3, 60_000)
    h = extract_hints("tv 1200 em 10 vezes", TODAY)
    assert (h.installments, h.amount_cents) == (10, 120_000)
    assert extract_hints("paguei dia 10 a luz 180", TODAY).installments is None
    assert extract_hints("#Pessoal pizza 50", TODAY).private is True
    assert extract_hints("#família mercado 30", TODAY).family is True
    assert extract_hints("mercado 30", TODAY) == extract_hints("mercado 30", TODAY)
    assert extract_hints("mercado 30", TODAY).private is False


def test_hints_agree_with_every_eval_case():
    """A camada determinística nunca contradiz o esperado do conjunto de avaliação."""
    today, cases = load_cases()
    for case in cases:
        expect, h = case["expect"], extract_hints(case["text"], today)
        if h.amount_cents is not None and "amount_cents" in expect:
            assert h.amount_cents == expect["amount_cents"], case["text"]
        if h.installments is not None:
            assert h.installments == expect.get("installments"), case["text"]
        if h.private:
            assert expect.get("private") is True, case["text"]
        if expect.get("private"):
            assert h.private, case["text"]
        if h.occurred_on and "occurred_on" in expect and expect["intent"] != "nova_conta_a_pagar":
            assert h.occurred_on.isoformat() == expect["occurred_on"], case["text"]
        if "amount_cents" in expect and expect["intent"] not in ("consultar_gastos",):
            assert h.amount_cents == expect["amount_cents"], case["text"]  # extrai todos os valores


def test_adversarial_input_is_bounded_and_fast():
    import time

    from app.core.money import MAX_CENTS

    bombs = [
        "mil e " * 50_000, "novecentos mil e " * 20_000, "1" * 100_000, "1." * 50_000,
        "dia " * 50_000, "9/" * 50_000, "3x " * 50_000, "#" * 100_000, "um milhão",
        "novecentos mil novecentos mil novecentos mil novecentos mil",
    ]  # fmt: skip
    start = time.monotonic()
    for b in bombs:
        for v in (parse_amount_words(b), extract_amount(b), parse_bare_amount(b)):
            assert v is None or (isinstance(v, int) and 0 < v <= MAX_CENTS)
        h = extract_hints(b, TODAY)
        assert h.amount_cents is None or 0 < h.amount_cents <= MAX_CENTS
        assert h.occurred_on is None or h.occurred_on.year > 1
    assert time.monotonic() - start < 2


@pytest.mark.parametrize("text", ["gastei 50 em 1/1/0000", "gastei 50 em 1/1/1999", "5/5/9999"])
def test_out_of_range_year_is_not_a_date_and_never_raises(text):
    assert resolve_date(text, TODAY) is None
    assert extract_hints(text, TODAY).occurred_on is None


def test_impossible_day_does_not_raise():
    assert resolve_date("gastei 50 em 31/02", TODAY) == date(2026, 2, 28)
    assert resolve_date("gastei 50 em 32/01", TODAY) is None


def merged(text, model_cents, intent="lancar_parcelado", installments=None):
    from app.assistant.intents import ParsedIntent
    from app.assistant.processor import merge_hints

    p = ParsedIntent.of(intent, amount_cents=model_cents, installments=installments)
    return merge_hints(p, extract_hints(text, TODAY))


def test_installments_keep_the_models_total_when_it_is_in_the_text():
    p, warn = merged("iphone 15 por 5000 em 12x", 500_000)
    assert (p.amount_cents, p.installments, p.intent, warn) == (
        500_000, 12, "lancar_parcelado", None,
    )  # fmt: skip
    p, warn = merged("comprei 2 pneus 800 em 4x", 80_000)
    assert (p.amount_cents, p.installments, warn) == (80_000, 4, None)


def test_installments_x_de_total_comes_from_the_text():
    p, warn = merged("tv em 3x de 500", 50_000)
    assert (p.amount_cents, p.installments, warn) == (150_000, 3, None)


def test_installments_model_amount_absent_from_text_single_amount_wins_with_warning():
    p, warn = merged("tv 600 em 3x", 123_400)
    assert p.amount_cents == 60_000 and warn is not None and "R$ 600,00" in warn
    p, warn = merged("iphone 15 por 5000 em 12x", 123_400)  # ambíguo: dois números, fica o modelo
    assert p.amount_cents == 123_400 and warn is None


def test_missing_model_amount_is_filled_from_text():
    p, _ = merged("tv 600 em 3x", None)
    assert p.amount_cents == 60_000
