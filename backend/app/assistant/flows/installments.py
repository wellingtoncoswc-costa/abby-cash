"""Marcar parcela de financiamento/consórcio como paga pelo chat: baixa histórica (sem
lançamento, em lote com "até a N") ou pagamento real (gera lançamento, pelo fluxo de pagar conta).
"Paguei o financiamento do carro" (sem nº de parcela) segue em `pay`."""

import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from app.assistant.flows import guided, pay
from app.assistant.flows.guided import ask, retry
from app.assistant.flows.payment import _match, _tokens
from app.assistant.flows.pockets import match_by_name, no_loan
from app.assistant.intents import ParsedIntent
from app.assistant.replies import NO_ACCOUNT, account_label
from app.assistant.turn import Draft, Pay, Turn
from app.core.money import format_brl
from app.core.text import fold
from app.domain.loans.models import Loan
from app.domain.loans.service import (
    list_installments,
    list_loans,
    loan_progress,
    materialize_installment,
    settle_installment,
    visible_loan,
)

_UNTIL = re.compile(r"\bate\s+(?:a\s+)?(?:parcela\s+)?(\d{1,3})\b")
_NUMBER = re.compile(r"\bparcela\s+(?:n\w*\s*)?(\d{1,3})\b|\b(\d{1,3})\s*a\s+parcela\b")
_PAID_ALREADY = "Já estava paga antes (só baixa, sem lançamento)"
_PAID_NOW = "Paguei agora (escolher conta e lançar)"


def refine(text: str, p: ParsedIntent) -> ParsedIntent:
    """ "paguei a parcela 12 do carro" / "já paguei até a 17 do consórcio" é baixar_parcela, mesmo
    que o modelo tenha dito pagar_conta; sem nº de parcela ("paguei o financiamento") não muda."""
    if p.intent not in ("pagar_conta", "baixar_parcela"):
        return p
    s = fold(text)
    loanish = p.intent == "baixar_parcela" or re.search(r"parcela|financiamento|consorcio", s)
    until, number = (_UNTIL.search(s) if loanish else None), _NUMBER.search(s)
    if until:
        n, through = int(until.group(1)), True
    elif number:
        n, through = int(number.group(1) or number.group(2)), False
    else:
        return p
    if not 1 <= n <= 480:
        return p
    return p.model_copy(
        update={"intent": "baixar_parcela", "installment_number": p.installment_number or n,
                "through": through or p.through}
    )  # fmt: skip


async def start(t: Turn, p: ParsedIntent, space_id: UUID) -> str:
    loans = await list_loans(t.session, viewer_id=t.user_id, space_id=space_id)
    if not loans:
        return no_loan()
    g: dict[str, Any] = {"flow": "settle", "space_id": str(space_id), "tries": 0}
    g["f"] = {"number": p.installment_number, "through": bool(p.through), "hint": p.account_hint}
    ids = match_by_name(p.pocket_hint, [(x.id, x.name) for x in loans])
    if len(ids) == 1 or (len(loans) == 1 and not p.pocket_hint):
        loan = next(x for x in loans if x.id in ids) if ids else loans[0]
        g["f"].update(loan_id=str(loan.id), loan=loan.name)
    else:
        shown = [x for x in loans if x.id in ids] or loans
        opts = [Pay(type="loan", id=x.id, label=x.name) for x in shown]
        return await ask(t, g, "loan", "Qual financiamento?", opts)
    return await advance(t, g)


async def advance(t: Turn, g: dict[str, Any]) -> str:
    f = g["f"]
    loan = await visible_loan(t.session, t.user_id, UUID(f["loan_id"]))  # membro do espaço
    name, total = loan.name, loan.installments_total
    if f["number"] is None or not 1 <= f["number"] <= total:
        q = f"Qual parcela do {name}? (1 a {total})"
        return await ask(t, g, "number", ("Esse número não existe. " if f["number"] else "") + q)
    n, through = f["number"], f["through"]
    ins = {i.number: i for i in await list_installments(t.session, loan)}
    if through:
        todo = [i.number for i in ins.values() if i.number <= n and i.state == "open"]
        if not todo:
            return f"Todas as parcelas até a {n} do {name} já estão pagas."
        f["todo"] = todo
        q = (
            f"Dar baixa (sem lançamento) em {len(todo)} parcelas do {name}, da 1 até a {n} "
            f"({n - len(todo)} já estavam pagas)? Responda com o número:\n1) Sim\n2) Não"
        )
        return await ask(t, g, "confirm", q)
    i = ins[n]
    if i.state == "paid_history":
        return f"A parcela {n}/{total} do {name} já estava baixada (paga antes, sem lançamento)."
    if i.state == "paid_real":
        return (
            f"A parcela {n}/{total} do {name} já foi paga com lançamento; "
            "pagamento real não se desfaz pelo chat."
        )
    if "mode" not in f:
        head = (
            f"Parcela {n}/{total} do {name} ({format_brl(i.amount_cents)}, "
            f"vence {i.due_on:%d/%m/%Y})."
        )
        return await ask(t, g, "mode", head, [_opt("1", _PAID_ALREADY), _opt("2", _PAID_NOW)])
    if f["mode"] == "history":
        try:
            await settle_installment(t.session, actor_id=t.user_id, loan_id=loan.id, number=n)
        except HTTPException as e:
            if e.status_code != 409:
                raise
            await t.session.rollback()
            return f"A parcela {n}/{total} do {name} tem pagamento parcial; não dá para baixar."
        return await _done(t, loan, f"✅ Parcela {n}/{total} do {name} baixada (sem lançamento).")
    return await _pay(t, g, loan)


def _opt(i: str, label: str) -> Pay:  # opção fixa: só o rótulo importa (a escolha é pelo nº)
    return Pay(type="loan", id=UUID(int=int(i)), label=label)


async def _done(t: Turn, loan: Loan, text: str) -> str:
    p = await loan_progress(t.session, loan)
    return f"{text} Pagas: {p.paid_count} de {loan.installments_total}."


async def _pay(t: Turn, g: dict[str, Any], loan: Loan) -> str:
    f = g["f"]
    ctx = await t.context(UUID(g["space_id"]))
    if "account_id" not in f:
        pays = [
            Pay(type="account", id=a.id, label=account_label(a.type, a.name)) for a in ctx.accounts
        ]
        if not pays:
            return NO_ACCOUNT
        hinted = _match([(a.id, a.name) for a in ctx.accounts], _tokens([f["hint"] or ""]))
        if len(hinted) == 1 and f["hint"]:
            pays = [x for x in pays if x.id in hinted]
        if len(pays) > 1:
            return await ask(t, g, "account", "De qual conta saiu?", pays)
        f["account_id"], f["account"] = str(pays[0].id), pays[0].label
    bill = await materialize_installment(
        t.session, actor_id=t.user_id, loan_id=loan.id, number=f["number"]
    )
    d = Draft(
        action="pay", p=ParsedIntent.of("pagar_conta"), space_id=loan.space_id, bill_id=bill.id,
        payment=Pay(type="account", id=UUID(f["account_id"]), label=f["account"]),
    )  # fmt: skip
    return await pay.run(t, d)


async def step(t: Turn, g: dict[str, Any], text: str, reply: str | None) -> str:
    s, f = g["step"], g["f"]
    if s == "confirm":
        ok = guided.yes_no(text)
        if ok is None:
            return await retry(t, g)
        return await _batch(t, g) if ok else "Ok, não dei baixa."
    if s == "number":
        w = text.strip()
        if not (w.isdigit() and 1 <= int(w) <= 480):
            return await retry(t, g)
        f["number"] = int(w)
    else:
        if (o := guided.pick(g, text)) is None:
            return await retry(t, g)
        if s == "loan":
            f.update(loan_id=str(o.id), loan=o.label)
        elif s == "mode":
            f["mode"] = "history" if o.label == _PAID_ALREADY else "real"
        else:
            f.update(account_id=str(o.id), account=o.label)
    return await advance(t, g)


async def _batch(t: Turn, g: dict[str, Any]) -> str:
    f = g["f"]
    loan = await visible_loan(t.session, t.user_id, UUID(f["loan_id"]))
    done = skipped = 0
    for n in f["todo"]:
        try:
            await settle_installment(t.session, actor_id=t.user_id, loan_id=loan.id, number=n)
            done += 1
        except HTTPException as e:
            if e.status_code != 409:
                raise
            await t.session.rollback()  # parcela paga/parcial no meio do caminho: segue
            skipped += 1
    tail = f" ({skipped} com pagamento parcial ficaram de fora)" if skipped else ""
    text = (
        f"✅ {done} parcelas do {loan.name} baixadas, da 1 até a {f['number']}, "
        f"sem lançamento{tail}."
    )
    return await _done(t, loan, text)
