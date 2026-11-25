import re
from uuid import UUID

from app.assistant.context import SpaceContext
from app.assistant.intents import ParsedIntent
from app.assistant.replies import account_label
from app.assistant.resolve import resolve_hint
from app.assistant.turn import Pay
from app.core.text import fold

_STOP = {
    "no", "na", "nos", "nas", "o", "a", "de", "do", "da", "dos", "das", "em", "pelo", "pela",
    "com", "meu", "minha", "conta", "cartao", "credito", "debito", "pix", "transferencia",
    "ted", "doc", "dinheiro", "carteira", "especie",
}  # fmt: skip
Choice = tuple[Pay | None, list[Pay]]  # (escolhida, opções para perguntar)


def _accounts(ctx: SpaceContext, only: set[UUID] | None = None) -> list[Pay]:
    return [
        Pay(type="account", id=a.id, label=account_label(a.type, a.name))
        for a in ctx.accounts
        if only is None or a.id in only
    ]


def _tokens(hints: list[str]) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", fold(" ".join(hints))) if w not in _STOP]


def _match(items: list[tuple[UUID, str]], tokens: list[str]) -> set[UUID]:
    """Itens (do próprio usuário) cujo nome contém o texto, ou parecido (difflib)."""
    found = {i for i, n in items if any(t in fold(n) for t in tokens)}
    if not found and (best := resolve_hint(" ".join(tokens), [n for _, n in items])):
        found = {i for i, n in items if n == best}
    return found


def choose_account(ctx: SpaceContext, hints: list[str]) -> Choice:
    """Dica da mensagem -> conta única -> pergunta. Sem dica ou com dica que não casa, pergunta:
    nunca assume a conta padrão em silêncio."""
    text = fold(" ".join(hints))
    everyone = _accounts(ctx)
    if not ctx.accounts:
        return None, []
    if re.search(r"\b(dinheiro|carteira|especie)\b", text):
        wallets = _accounts(ctx, {a.id for a in ctx.accounts if a.type == "wallet"})
        return (wallets[0], []) if len(wallets) == 1 else (None, wallets or everyone)
    if tokens := _tokens(hints):
        found = _accounts(ctx, _match([(a.id, a.name) for a in ctx.accounts], tokens))
        return (found[0], []) if len(found) == 1 else (None, found or everyone)
    return (everyone[0], []) if len(everyone) == 1 else (None, everyone)


def choose_card(ctx: SpaceContext, hints: list[str]) -> Choice:
    cards = [Pay(type="card", id=c.id, label=f"Cartão {c.name}") for c in ctx.cards]
    if tokens := _tokens(hints):
        ids = _match([(c.id, c.name) for c in ctx.cards], tokens)
        found = [c for c in cards if c.id in ids]
        return (found[0], []) if len(found) == 1 else (None, found or cards)
    return (cards[0], []) if len(cards) == 1 else (None, cards)


def choose_payment(ctx: SpaceContext, p: ParsedIntent, *, income: bool) -> Choice:
    """Cartão quando há parcelas, dica de cartão ou a palavra cartão/crédito; senão, conta."""
    hints = [h for h in (p.card_hint, p.account_hint) if h]
    wants_card = not income and (
        (p.installments or 1) > 1
        or bool(p.card_hint)
        or re.search(r"cartao|credito", fold(" ".join(hints))) is not None
    )
    return choose_card(ctx, hints) if wants_card else choose_account(ctx, hints)


def pick_option(options: list[Pay], text: str) -> Pay | None:
    """Resposta a uma lista numerada: o número ou parte única do nome."""
    s = fold(text).strip()
    if re.fullmatch(r"\d{1,2}", s):
        n = int(s)
        return options[n - 1] if 1 <= n <= len(options) else None
    if len(s) >= 3:
        found = [o for o in options if s in fold(o.label)]
        return found[0] if len(found) == 1 else None
    return None
