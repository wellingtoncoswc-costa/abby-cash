"""Motor das conversas guiadas (criar caixinha/financiamento, baixar parcela): uma pergunta por
vez; o rascunho `g` (JSON) vai inteiro para `conversation_state`. Cada resposta consome o estado
antes de agir (processor.resume), então nada roda duas vezes."""

from typing import Any

from app.assistant.flows.payment import pick_option
from app.assistant.replies import options_text
from app.assistant.shortcuts import answer, try_shortcut
from app.assistant.state import set_state
from app.assistant.turn import Pay, Turn

KIND = "guided"
CANCELLED = "Ok, cancelei. Mande de novo quando quiser."


async def ask(
    t: Turn, g: dict[str, Any], step: str, question: str, options: list[Pay] | None = None
) -> str:
    """Grava a pergunta (e as opções numeradas, se houver) e devolve o texto."""
    if options is not None:
        question = options_text(question, [o.label for o in options])
    g.update(
        step=step, q=question, tries=0, opts=[o.model_dump(mode="json") for o in options or []]
    )
    await set_state(t.session, t.user_id, t.channel, KIND, {"g": g}, t.now)
    return question


async def retry(t: Turn, g: dict[str, Any]) -> str:
    """Resposta fora do esperado: repete a pergunta uma vez; na segunda, cancela."""
    if g.get("tries", 0) >= 1:
        return CANCELLED
    g["tries"] = 1
    await set_state(t.session, t.user_id, t.channel, KIND, {"g": g}, t.now)
    return f"Não entendi. {g['q']}"


def pick(g: dict[str, Any], text: str) -> Pay | None:
    return pick_option([Pay.model_validate(o) for o in g["opts"]], text)


def yes_no(text: str) -> bool | None:
    s = text.strip()
    reply = answer(text)
    if s == "1" or reply == "sim":
        return True
    return False if s == "2" or reply == "nao" else None


def is_command(text: str) -> bool:
    """Texto livre que é um comando (saldo, ajuda...): não serve de nome."""
    shortcut = try_shortcut(text)
    return shortcut is not None and shortcut.choice is None
