import re
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
        ("hoje 10", date(2026, 11, 25)), ("na sexta 50", date(2026, 11, 20)),
        ("quarta passada 20", date(2026, 11, 18)), ("segunda-feira 10", date(2026, 11, 23)),
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
        bare_words = h.amount_cents is None and not re.search(
            r"\d|reais|real|conto|mil", case["text"]
        )
        if (
            "amount_cents" in expect
            and expect["intent"] not in ("consultar_gastos",)
            and not bare_words
        ):
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


def test_amount_in_words_needs_a_unit():
    assert extract_amount("tres amigos foram") is None
    assert extract_amount("comprei dois pasteis") is None
    assert extract_amount("gastei quarenta reais") == 4_000
    assert extract_amount("gastei dois mil") == 200_000
    assert parse_bare_amount("quarenta") == 4_000  # resposta a "quanto foi?"


def test_extract_amount_prefers_marked_then_largest():
    assert extract_amount("2 camisetas 100 em 2x") == 10_000
    assert extract_amount("uber 2 pessoas 23") == 2_300
    assert extract_amount("2 camisetas R$ 100") == 10_000
    assert extract_amount("100 reais em 2 camisetas") == 10_000
    h = extract_hints("2 camisetas 100 em 2x", TODAY)
    assert (h.amount_cents, h.installments) == (10_000, 2)


@pytest.mark.parametrize(
    "text",
    ["segunda via do documento 20", "quarta parcela do carro 300", "na quarta parcela 10",
     "sexta 50", "gastei 10 na segunda via"],
)  # fmt: skip
def test_weekday_words_without_context_do_not_shift_the_date(text):
    assert extract_hints(text, TODAY).weekday_on is None
    assert resolve_date(text, TODAY) is None


@pytest.mark.parametrize(
    ("text", "want"),
    [("sexta passada 50", date(2026, 11, 20)), ("sexta-feira 5", date(2026, 11, 20)),
     ("domingo 30", date(2026, 11, 22)), ("na segunda 5", date(2026, 11, 23))],
)  # fmt: skip
def test_weekday_with_context_is_a_weak_hint(text, want):
    h = extract_hints(text, TODAY)
    assert h.occurred_on is None and h.weekday_on == want


def test_a_numeric_date_beats_a_weekday():
    h = extract_hints("domingo 23/11 uber 10", TODAY)
    assert h.occurred_on == date(2026, 11, 23) and h.weekday_on is None


@pytest.mark.parametrize("text", ["31/02 uber 10", "gastei 10 em 30/02/2026", "29/02 x"])
def test_impossible_dates_are_flagged_not_clamped(text):
    h = extract_hints(text, TODAY)
    assert h.bad_date and h.occurred_on is None


def test_dia_31_in_a_30_day_month_goes_back_to_a_real_31():
    assert resolve_date("dia 31 luz", TODAY) == date(2026, 10, 31)
