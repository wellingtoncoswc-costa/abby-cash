import pytest

from app.core.money import format_brl, parse_brl


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("1.234,56", 123456),
        ("1234.56", 123456),
        ("R$45", 4500),
        ("R$ 45", 4500),
        ("45 reais", 4500),
        ("45,5", 4550),
        ("45", 4500),
        ("1.234", 123400),
        ("0,99", 99),
        ("0.500", 50),
    ],
)
def test_parse_brl_valid(text, cents):
    assert parse_brl(text) == cents


@pytest.mark.parametrize(
    "text",
    [
        "0",
        "0,00",
        "-10",
        "R$ -5",
        "abc",
        "",
        "nan",
        "inf",
        "1,2,3",
        "1e30",
        "1E5",
        "1_000",
        "2000000000",
        "1.000.000.000,01",
        "1,000.50",
        "1.2,5",
        "12.5,00",
        "1.000,5.0",
        "0,025",
        "1234.567",
    ],
)
def test_parse_brl_rejects_non_positive_or_garbage(text):
    assert parse_brl(text) is None


def test_format_brl():
    assert format_brl(123456) == "R$ 1.234,56"
    assert format_brl(4500) == "R$ 45,00"
    assert format_brl(5) == "R$ 0,05"
    assert format_brl(100000000) == "R$ 1.000.000,00"
