import re
from uuid import UUID

from fastapi import HTTPException

from app.assistant import links
from app.assistant.context import SpaceContext
from app.assistant.flows.common import ask
from app.assistant.flows.payment import _match, _tokens
from app.assistant.intents import ParsedIntent
from app.assistant.links import with_link
from app.assistant.replies import FUTURE_DATE, ZERO, account_label, options_text, tx_line
from app.assistant.turn import Draft, Pay, Turn
from app.core.money import format_brl
from app.core.text import fold
from app.domain.pockets.service import account_pockets_cents
from app.domain.transactions.service import account_balance, create_transaction

TWO_ACCOUNTS = "Para transferir preciso de pelo menos duas contas. Cadastre no painel web (Contas)."
_TYPE = {"poupanca": "savings", "corrente": "checking", "dinheiro": "wallet", "carteira": "wallet"}


def _find(
    ctx: SpaceContext, hint: str | None, skip: UUID | None = None
) -> tuple[Pay | None, list[Pay]]:
    """Conta da dica (nome ou tipo: poupança/corrente/carteira) ou a lista para perguntar."""
    accs = [a for a in ctx.accounts if a.id != skip]
    pays = {a.id: Pay(type="account", id=a.id, label=account_label(a.type, a.name)) for a in accs}
    cand = accs
    if tokens := [w for w in _tokens([hint or ""]) if w not in _TYPE]:
        found = _match([(a.id, a.name) for a in accs], tokens)
        cand = [a for a in accs if a.id in found] or accs
    if types := {_TYPE[w] for w in re.findall(r"[a-z]+", fold(hint or "")) if w in _TYPE}:
        cand = [a for a in cand if a.type in types] or cand
    if hint and len(cand) == 1:
        return pays[cand[0].id], []
    return None, [pays[a.id] for a in cand]


async def start(t: Turn, p: ParsedIntent, space_id: UUID) -> str:
    return await run(t, Draft(action="transfer", p=p, space_id=space_id))


async def run(t: Turn, d: Draft) -> str:
    """Transfere na hora (reversível por "apagar"). Pergunta uma coisa por vez: origem, destino."""
    p = d.p
    if p.amount_cents is None or p.amount_cents <= 0:
        prefix = "" if p.amount_cents is None else ZERO + " "
        p.amount_cents = None
        return await ask(t, d, "amount", prefix + "Quanto você transferiu? (ex.: 300)")
    if p.occurred_on is not None and p.occurred_on > t.today:
        return FUTURE_DATE
    ctx = await t.context(d.space_id)
    if len(ctx.accounts) < 2:
        return TWO_ACCOUNTS
    if d.payment is None:
        src, options = _find(ctx, p.account_hint)
        if src is None:
            d.options = options
            return await ask(
                t, d, "payment", options_text("De qual conta saiu?", [o.label for o in options])
            )
        d.payment = src
    if d.to is None:
        dst, options = _find(ctx, p.to_account_hint)  # inclui a origem: "do nubank pro nubank"
        if dst is not None and dst.id == d.payment.id:
            return f"{d.payment.label} é a origem e o destino. Diga duas contas diferentes."
        if dst is None:
            d.options = [o for o in options if o.id != d.payment.id]
            return await ask(
                t, d, "dest",
                options_text("Para qual conta foi?", [o.label for o in d.options]),
            )  # fmt: skip
        d.to = dst
    source = next(a for a in ctx.accounts if a.id == d.payment.id)
    try:
        tx = await create_transaction(
            t.session, actor_id=t.user_id, space_id=source.space_id, type="transfer",
            amount_cents=p.amount_cents, occurred_on=p.occurred_on or t.today,
            account_id=d.payment.id, counter_account_id=d.to.id, origin=t.channel,
            source_message_id=t.message_id,
        )  # fmt: skip
    except HTTPException as e:
        if e.detail != "insufficient_available":
            raise
        await t.session.rollback()
        free = await account_balance(t.session, source.id) - await account_pockets_cents(
            t.session, source.id
        )
        return (
            f"A conta {source.name} tem só {format_brl(max(free, 0))} disponíveis (fora das "
            f"caixinhas); você pediu {format_brl(p.amount_cents)}."
        )
    return with_link(await tx_line(t.session, tx, t.today, hint=False), links.lancamentos())
