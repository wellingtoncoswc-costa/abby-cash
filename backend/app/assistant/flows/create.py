"""Criar caixinha e financiamento/consórcio por conversa guiada (mesmas regras da API)."""

import re
from datetime import date
from typing import Any
from uuid import UUID

from app.assistant.amounts import parse_bare_amount
from app.assistant.flows import guided
from app.assistant.flows.guided import ask, retry
from app.assistant.flows.payment import _match, _tokens
from app.assistant.flows.pockets import _KIND, _pct, is_create_request
from app.assistant.intents import Intent, ParsedIntent
from app.assistant.replies import NO_ACCOUNT, account_label
from app.assistant.turn import Pay, Turn
from app.core.dates import add_months
from app.core.money import MAX_CENTS, format_brl
from app.core.text import clean_text, fold
from app.domain.loans.service import create_loan, loan_progress
from app.domain.pockets.service import create_pocket

INTENTS = {"criar_caixinha", "criar_financiamento", "baixar_parcela"}
CDI_QUESTION = (
    "Quanto ela rende, em % do CDI? Responda com o número:\n"
    "1) 100%  2) 110%  3) 120%  4) outro (ou digite o valor, ex.: 115)"
)
_PRESET = {"1": 10_000, "2": 11_000, "3": 12_000}
_CDI = re.compile(r"(\d{1,4})(?:[.,](\d{1,2}))?\s*(%)?(?:\s*do\s*cdi)?")
_DATE = re.compile(r"(?:dia\s+)?(\d{1,2})(?:/(\d{1,2})(?:/(\d{4}))?)?")
_NEG = {"nao", "nenhuma", "nenhum", "zero", "0"}


def parse_cdi_bp(text: str) -> int | None:
    """ "115" -> 11500, "102,5%" -> 10250, "120% do CDI" -> 12000; só inteiros (sem float).
    Faixa 0,01%..1000%."""
    m = _CDI.fullmatch(fold(text).strip())
    if not m:
        return None
    bp = int(m.group(1)) * 100 + int((m.group(2) or "").ljust(2, "0") or 0)
    return bp if 1 <= bp <= 100_000 else None


def parse_due(text: str, today: date) -> date | None:
    """ "10/12/2026", "10/12" (próxima ocorrência) ou "dia 10"; None se não existe/inválida."""
    m = _DATE.fullmatch(fold(text).strip())
    if not m:
        return None
    day, month, year = int(m.group(1)), m.group(2), m.group(3)
    try:
        if year:
            return date(int(year), int(month), day)
    except ValueError:
        return None
    if month and not 1 <= int(month) <= 12:
        return None
    for i in range(48):  # próxima data (hoje ou depois) que exista: "dia 31", 29/02
        base = add_months(today.replace(day=1), i)
        try:
            found = date(base.year, int(month) if month else base.month, day)
        except ValueError:
            continue
        if found >= today:
            return found
    return None


def _valid_due(d: date | None) -> date | None:
    return d if d and date(2000, 1, 1) <= d <= date(2100, 12, 31) else None


# --- início ---------------------------------------------------------------------------------

_THING = re.compile(r"\b(caixinha|cofrinho|financiamento|consorcio)\b")


def rescue(text: str, p: ParsedIntent | None, warn: str | None) -> ParsedIntent | None:
    """Pedido de criar sem o modelo (IA fora/indecisa): o fluxo guiado pergunta tudo."""
    if not is_create_request(text) or (p is not None and p.intent not in _UNSURE and not warn):
        return p
    word = _THING.search(fold(text))
    assert word is not None
    intent: Intent = (
        "criar_caixinha" if word.group(1) in ("caixinha", "cofrinho") else "criar_financiamento"
    )
    return ParsedIntent.of(intent)


_UNSURE = {"desconhecido", "ajuda", "lancar_despesa", "lancar_receita", "lancar_parcelado"}


async def start(t: Turn, p: ParsedIntent, space_id: UUID, text: str) -> str:
    g: dict[str, Any] = {"space_id": str(space_id), "tries": 0}
    name = clean_text(p.new_name or "", 100)
    f: dict[str, Any] = {"name": name} if name else {}
    if p.intent == "criar_caixinha":
        g["flow"] = "pocket"
        if p.cdi_bp is not None:
            f["cdi_bp"] = p.cdi_bp
        if p.account_hint:
            ctx = await t.context(space_id)
            mine = [a for a in ctx.accounts if a.space_id == space_id]
            found = _match([(a.id, a.name) for a in mine], _tokens([p.account_hint]))
            if len(found) == 1:
                a = next(x for x in mine if x.id in found)
                f.update(account_id=str(a.id), account=account_label(a.type, a.name))
    else:
        g["flow"] = "loan"
        s = fold(text)
        kind = "consortium" if "consorcio" in s else "financing" if "financiamento" in s else None
        if kind := kind or p.loan_kind:
            f["kind"] = kind
        if p.amount_cents:
            f["cents"] = p.amount_cents
        if p.loan_installments:
            f["total"] = p.loan_installments
        if p.first_due_on and _valid_due(p.first_due_on):
            f["due"] = p.first_due_on.isoformat()
        if p.paid_installments is not None:
            f["paid"] = p.paid_installments
    g["f"] = f
    return await advance(t, g)


# --- próxima pergunta -----------------------------------------------------------------------


def _where(label: str) -> str:
    return f"na conta {label[6:]}" if label.startswith("Conta ") else f"em {label}"


async def advance(t: Turn, g: dict[str, Any]) -> str:
    return await (_pocket if g["flow"] == "pocket" else _loan)(t, g)


async def _pocket(t: Turn, g: dict[str, Any]) -> str:
    f, space_id = g["f"], UUID(g["space_id"])
    if "name" not in f:
        return await ask(t, g, "name", "Qual o nome da caixinha?")
    if "account_id" not in f:
        ctx = await t.context(space_id)
        accs = [a for a in ctx.accounts if a.space_id == space_id]
        if not accs:
            return NO_ACCOUNT
        pays = [Pay(type="account", id=a.id, label=account_label(a.type, a.name)) for a in accs]
        if len(pays) > 1:
            return await ask(t, g, "account", "Em qual conta fica a caixinha?", pays)
        f.update(account_id=str(pays[0].id), account=pays[0].label)
    if "cdi_bp" not in f:
        return await ask(t, g, "cdi", CDI_QUESTION)
    q = f"Criar caixinha {f['name']} {_where(f['account'])}, rendendo {_pct(f['cdi_bp'])}?"
    return await ask(t, g, "confirm", q + " Responda com o número:\n1) Sim\n2) Não")


async def _loan(t: Turn, g: dict[str, Any]) -> str:
    f = g["f"]
    if "kind" not in f:
        q = "É financiamento ou consórcio? Responda com o número:\n1) Financiamento\n2) Consórcio"
        return await ask(t, g, "kind", q)
    word = _KIND[f["kind"]]
    if "name" not in f:
        return await ask(t, g, "name", f"Qual o nome do {word}? (ex.: Carro)")
    if "cents" not in f:
        return await ask(t, g, "cents", "Qual o valor da parcela? (ex.: 1.890)")
    if "total" not in f:
        return await ask(t, g, "total", "Quantas parcelas no total? (1 a 480)")
    if "due" not in f:
        q = "Qual a data do 1º vencimento? (ex.: 10/12/2026, 10/12 ou dia 10)"
        return await ask(t, g, "due", q)
    if "paid" not in f or f["paid"] > f["total"]:
        q = "Quantas parcelas você já pagou antes de cadastrar? (0 se nenhuma)"
        return await ask(t, g, "paid", q)
    due, paid = date.fromisoformat(f["due"]), f["paid"]
    q = (
        f"Criar {word} {f['name']}: {f['total']} parcelas de {format_brl(f['cents'])}, "
        f"1º vencimento {due:%d/%m/%Y}" + (f", {paid} já pagas" if paid else "") + "?"
    )
    return await ask(t, g, "confirm", q + " Responda com o número:\n1) Sim\n2) Não")


# --- respostas ------------------------------------------------------------------------------


async def step(t: Turn, g: dict[str, Any], text: str, reply: str | None) -> str:
    s, f = g["step"], g["f"]
    if s == "confirm":
        ok = guided.yes_no(text)
        if ok is None:
            return await retry(t, g)
        if not ok:
            return "Ok, não criei."
        return await (_create_pocket if g["flow"] == "pocket" else _create_loan)(t, g)
    if reply == "nao" and s not in ("paid",):
        return "Ok, cancelei."
    n = text.strip()
    match s:
        case "name":
            name = clean_text(text, 100)
            if not name or guided.is_command(text):
                return await retry(t, g)
            f["name"] = name
        case "account":
            if (a := guided.pick(g, text)) is None:
                return await retry(t, g)
            f.update(account_id=str(a.id), account=a.label)
        case "cdi":
            if bp := _PRESET.get(n):
                f["cdi_bp"] = bp
            elif n == "4":
                return await ask(t, g, "cdi_other", "Qual percentual do CDI? (ex.: 102,5)")
            elif bp := parse_cdi_bp(text):
                f["cdi_bp"] = bp
            else:
                return await retry(t, g)
        case "cdi_other":
            if not (bp := parse_cdi_bp(text)):
                return await retry(t, g)
            f["cdi_bp"] = bp
        case "kind":
            w = fold(text)
            kind = {"1": "financing", "2": "consortium"}.get(n) or (
                "consortium" if "consorc" in w else "financing" if "financ" in w else None
            )
            if kind is None:
                return await retry(t, g)
            f["kind"] = kind
        case "cents":
            cents = parse_bare_amount(text)
            if not cents or cents > MAX_CENTS:
                return await retry(t, g)
            f["cents"] = cents
        case "total":
            if not (n.isdigit() and 1 <= int(n) <= 480):
                return await retry(t, g)
            f["total"] = int(n)
        case "due":
            if (due := _valid_due(parse_due(text, t.today))) is None:
                return await retry(t, g)
            f["due"] = due.isoformat()
        case "paid":
            w = fold(text).strip()
            paid = 0 if w in _NEG else int(w) if w.isdigit() else -1
            if not 0 <= paid <= f["total"]:
                return await retry(t, g)
            f["paid"] = paid
    return await advance(t, g)


# --- execução -------------------------------------------------------------------------------


async def _create_pocket(t: Turn, g: dict[str, Any]) -> str:
    f = g["f"]
    await create_pocket(
        t.session, actor_id=t.user_id, space_id=UUID(g["space_id"]),
        account_id=UUID(f["account_id"]), name=f["name"], cdi_bp=f["cdi_bp"],
    )  # fmt: skip
    return f"✅ Caixinha {f['name']} criada {_where(f['account'])}, rendendo {_pct(f['cdi_bp'])}."


async def _create_loan(t: Turn, g: dict[str, Any]) -> str:
    f = g["f"]
    loan = await create_loan(
        t.session, actor_id=t.user_id, space_id=UUID(g["space_id"]), kind=f["kind"],
        name=f["name"], installment_cents=f["cents"], installments_total=f["total"],
        first_due_on=date.fromisoformat(f["due"]), paid_installments=f["paid"],
    )  # fmt: skip
    prog = await loan_progress(t.session, loan)
    out = (
        f"✅ {_KIND[f['kind']].capitalize()} {f['name']} criado: {f['total']} parcelas de "
        f"{format_brl(f['cents'])}"
    )
    if f["paid"]:
        out += f" · {f['paid']} já baixadas"
    if prog.next_due_on:
        out += f" · próxima em {prog.next_due_on:%d/%m/%Y}"
    return out + "."
