import re
from typing import Any, Literal

from app.assistant.intents import Intent, ParsedIntent
from app.core.text import fold

_COMMANDS: dict[str, ParsedIntent] = {}


def _register(intent: Intent, *phrases: str, **fields: Any) -> None:
    for p in phrases:
        _COMMANDS[p] = ParsedIntent.of(intent, **fields)


_register("pagar_conta", "paguei", "pago", "quitei")
_register("corrigir", "corrigir", "corrige", "errei", "corrigir ultimo")
_register(
    "apagar", "apagar", "apaga", "apagar ultimo", "apaga ultimo", "apagar o ultimo", "desfazer",
    "excluir ultimo",
)  # fmt: skip
_register("consultar_saldo", "saldo", "meu saldo", "qual o saldo", "qual meu saldo")
_register("consultar_teto", "teto", "meu teto", "como esta o teto")
_register("consultar_faturas", "fatura", "faturas", "minhas faturas")
_register("consultar_gastos", "gastos", "meus gastos", "quanto gastei", period="mes")
_register("ajuda", "ajuda", "help", "menu", "comandos", "start")

_YES = {"sim", "s", "isso", "ok", "pode", "confirmo", "certo", "yes"}
_NO = {"nao", "n", "no", "negativo"}
_CANCEL = {"cancelar", "cancela", "deixa pra la", "esquece", "esquece isso", "desisti"}


def _clean(text: str) -> str:
    s = re.sub(r"[^\w\s]", " ", fold(text)).strip()  # sem pontuação nem "/"
    return " ".join(s.split())


def try_shortcut(text: str) -> ParsedIntent | None:
    """Comandos simples resolvidos sem LLM; None = precisa interpretar."""
    s = _clean(text)
    if re.fullmatch(r"\d{1,2}", s):
        return ParsedIntent.of("desconhecido", choice=int(s))
    return _COMMANDS[s].model_copy() if s in _COMMANDS else None


def answer(text: str) -> Literal["sim", "nao", "cancelar"] | None:
    """Resposta curta a uma pergunta pendente."""
    s = _clean(text)
    if s in _YES:
        return "sim"
    if s in _NO:
        return "nao"
    return "cancelar" if s in _CANCEL else None
