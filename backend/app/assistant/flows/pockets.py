import re
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.assistant import links
from app.assistant.flows.common import ask
from app.assistant.intents import ParsedIntent
from app.assistant.replies import ZERO, options_text
from app.assistant.resolve import resolve_hint
from app.assistant.turn import Draft, Pay, Turn
from app.core.money import format_brl
from app.core.text import fold
from app.domain.accounts.models import Account
from app.domain.errors import DomainError
from app.domain.loans.models import Loan
from app.domain.loans.service import list_loans, loan_progress
from app.domain.pockets.models import Pocket
from app.domain.pockets.service import (
    account_pockets_cents,
    deposit,
    pocket_stats,
    withdraw,
)
from app.domain.spaces.access import require_member
from app.domain.transactions.service import account_balance


def no_pocket() -> str:
    return (
        'Você ainda não tem caixinhas. Diga "criar caixinha" e eu cadastro por aqui, '
        f"ou use o painel:\n{links.caixinhas()}"
    )


def no_loan() -> str:
    return (
        'Você ainda não tem financiamentos. Diga "cadastrar financiamento" e eu cadastro por '
        f"aqui, ou use o painel:\n{links.financiamentos()}"
    )


_CREATE = re.compile(
    r"\b(criar|cria|crie|abrir|abre|abra|cadastrar|cadastra|cadastre)\b"
)  # fmt: skip
_THING = re.compile(r"\b(caixinha|cofrinho|financiamento|consorcio)\b")
_NOISE = re.compile(r"\b(caixinha|cofrinho|financiamento|consorcio|do|da|de|na|no)\b")


def is_create_request(text: str) -> bool:
    s = fold(text)
    return bool(_CREATE.search(s) and _THING.search(s))


def _key(hint: str | None) -> str:
    return " ".join(_NOISE.sub(" ", fold(hint or "")).split())


def match_by_name(hint: str | None, items: list[tuple[UUID, str]]) -> list[UUID]:
    """Itens cujo nome contém o texto do usuário (sem acento/caixa) ou é parecido."""
    if not (key := _key(hint)):
        return []
    found = [i for i, n in items if key in fold(n)]
    if not found and (best := resolve_hint(key, [n for _, n in items])):
        found = [i for i, n in items if n == best]
    return found


async def guardar_resgatar(t: Turn, p: ParsedIntent, space_id: UUID) -> str:
    return await run(t, Draft(action="pocket", p=p, space_id=space_id))


async def run(t: Turn, d: Draft) -> str:
    """Guarda/resgata na hora (reversível). Sem nome e com várias caixinhas, pergunta por número
    (a resposta chega como `payment`, o mesmo estado de escolha das contas)."""
    p, saving = d.p, d.p.intent == "guardar_caixinha"
    if p.amount_cents is None or p.amount_cents <= 0:
        prefix = "" if p.amount_cents is None else ZERO + " "
        p.amount_cents = None
        question = "Quanto você guardou? (ex.: 200)" if saving else "Quanto você tirou? (ex.: 100)"
        return await ask(t, d, "amount", prefix + question)
    ctx = await t.context(d.space_id)
    if not ctx.pockets:
        return no_pocket()
    if d.payment is None:
        ids = match_by_name(p.pocket_hint, [(x.id, x.name) for x in ctx.pockets])
        only = len(ctx.pockets) == 1 and not _key(p.pocket_hint)
        if len(ids) == 1 or only:
            pick = ctx.pockets[0] if only else next(x for x in ctx.pockets if x.id == ids[0])
            d.payment = Pay(type="pocket", id=pick.id, label=pick.name)
        else:
            shown = [x for x in ctx.pockets if x.id in ids] or ctx.pockets
            d.options = [Pay(type="pocket", id=x.id, label=x.name) for x in shown]
            ask_for = "Em qual caixinha?" if saving else "De qual caixinha?"
            return await ask(t, d, "payment", options_text(ask_for, [o.label for o in d.options]))
    name, amount = d.payment.label, p.amount_cents
    move = deposit if saving else withdraw
    try:
        await move(
            t.session, actor_id=t.user_id, pocket_id=d.payment.id, amount_cents=amount,
            origin=t.channel, source_message_id=t.message_id,
        )  # fmt: skip
    except (HTTPException, DomainError) as e:
        code = e.detail if isinstance(e, HTTPException) else str(e)
        if code not in ("insufficient_available", "insufficient_balance"):
            raise
        await t.session.rollback()  # o resgate pode ter creditado rendimento antes de falhar
        return await _short(t, d.payment.id, name, amount, saving)
    stats = await pocket_stats(t.session, d.payment.id, t.today)
    verb = f"{format_brl(amount)} guardados em" if saving else f"{format_brl(amount)} resgatados de"
    return f"✅ {verb} {name} · saldo {format_brl(stats.balance)}"


async def _short(t: Turn, pocket_id: UUID, name: str, amount: int, saving: bool) -> str:
    if not saving:
        have = (await pocket_stats(t.session, pocket_id, t.today)).balance
        return f"A caixinha {name} tem só {format_brl(have)}; você pediu {format_brl(amount)}."
    pocket = await t.session.get(Pocket, pocket_id)
    assert pocket is not None
    account = await t.session.get(Account, pocket.account_id)
    assert account is not None
    free = await account_balance(t.session, account.id) - await account_pockets_cents(
        t.session, account.id
    )
    return (
        f"A conta {account.name} tem só {format_brl(max(free, 0))} disponíveis (fora das "
        f"caixinhas); você pediu {format_brl(amount)}."
    )


def _pct(cdi_bp: int) -> str:
    whole, frac = divmod(cdi_bp, 100)
    return f"{whole},{frac:02d}".rstrip("0").rstrip(",") + "% do CDI"


async def caixinhas(t: Turn, space_id: UUID) -> str:
    await require_member(t.session, t.user_id, space_id)
    pockets = list(
        await t.session.scalars(
            select(Pocket)
            .where(Pocket.space_id == space_id, Pocket.closed_at.is_(None))
            .order_by(Pocket.name)
        )
    )
    if not pockets:
        return no_pocket()
    lines, total, accounts = [], 0, []
    for x in pockets:
        s = await pocket_stats(t.session, x.id, t.today)
        total += s.balance
        accounts.append(x.account_id)
        lines.append(
            f"• {x.name}: {format_brl(s.balance)} · {_pct(x.cdi_bp)} · "
            f"rendeu {format_brl(s.month_yield)} no mês"
        )
    out = ["🎯 Caixinhas:", *lines, f"Total: {format_brl(total)}"]
    for acc_id in dict.fromkeys(accounts):
        acc = await t.session.get(Account, acc_id)
        if acc is not None:
            free = await account_balance(t.session, acc.id) - await account_pockets_cents(
                t.session, acc.id
            )
            out.append(f"Disponível na conta {acc.name}: {format_brl(free)}")
    return links.with_link("\n".join(out), links.caixinhas())


_KIND = {"financing": "financiamento", "consortium": "consórcio"}


async def financiamentos(t: Turn, p: ParsedIntent, space_id: UUID) -> str:
    loans = await list_loans(t.session, viewer_id=t.user_id, space_id=space_id)
    if not loans:
        return no_loan()
    ids = match_by_name(p.pocket_hint, [(x.id, x.name) for x in loans])
    if p.pocket_hint and not ids:
        return "Não achei esse financiamento. Os seus: " + ", ".join(x.name for x in loans) + "."
    lines = []
    for x in loans:
        if ids and x.id not in ids:
            continue
        lines.append(await _loan_line(t, x, detail=bool(ids)))
    return links.with_link("🎯 Financiamentos:\n" + "\n".join(lines), links.financiamentos())


async def _loan_line(t: Turn, x: Loan, *, detail: bool) -> str:
    g = await loan_progress(t.session, x)
    head = (
        f"• {x.name} ({_KIND[x.kind]}): {g.paid_count} de {x.installments_total} pagas · "
        f"faltam {format_brl(g.remaining_cents)}"
    )
    if g.next_due_on is None:
        return head + " · quitado" if g.remaining_count == 0 else head
    head += f" · próxima {format_brl(x.installment_cents)} em {g.next_due_on:%d/%m}"
    if detail:
        head += f" · termina em {g.last_due_on:%m/%Y}"
    return head
