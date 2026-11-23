import pytest

from app.assistant.shortcuts import answer, try_shortcut


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("paguei", "pagar_conta"),
        ("Paguei!", "pagar_conta"),
        ("corrigir", "corrigir"),
        ("apagar último", "apagar"),
        ("Apagar ultimo.", "apagar"),
        ("saldo", "consultar_saldo"),
        ("/saldo", "consultar_saldo"),
        ("teto", "consultar_teto"),
        ("faturas", "consultar_faturas"),
        ("ajuda", "ajuda"),
        ("/start", "ajuda"),
    ],
)
def test_shortcuts_without_llm(text, intent):
    got = try_shortcut(text)
    assert got is not None and got.intent == intent and got.confidence == 1.0


def test_shortcut_number_is_a_list_choice():
    got = try_shortcut("2")
    assert got is not None and got.intent == "desconhecido" and got.choice == 2
    assert try_shortcut("45").choice == 45  # type: ignore[union-attr]
    assert try_shortcut("123") is None  # 3 dígitos: pode ser um valor
    assert try_shortcut("0") is None and try_shortcut("05") is None


@pytest.mark.parametrize(
    "text", ["gastei 45 mercado", "saldo da carteira ontem", "paguei 500 da fatura", ""]
)
def test_non_commands_need_the_llm(text):
    assert try_shortcut(text) is None


def test_shortcut_results_are_independent_copies():
    a = try_shortcut("saldo")
    assert a is not None
    a.amount_cents = 1
    assert try_shortcut("saldo").amount_cents is None  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("text", "want"),
    [("sim", "sim"), ("Sim!", "sim"), ("não", "nao"), ("nao", "nao"), ("cancelar", "cancelar"),
     ("deixa pra lá", "cancelar"), ("talvez", None)],
)  # fmt: skip
def test_yes_no_cancel(text, want):
    assert answer(text) == want
