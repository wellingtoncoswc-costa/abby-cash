from uuid import UUID

from app.assistant.flows.common import ask, tag_origin
from app.assistant.flows.launch import resolve_category
from app.assistant.flows.payment import choose_account
from app.assistant.intents import ParsedIntent
from app.assistant.replies import NO_ACCOUNT, ZERO, options_text
from app.assistant.resolve import resolve_hint
from app.assistant.turn import Draft, Turn
from app.core.money import format_brl
from app.core.text import fold
from app.domain.bills.service import create_bill
from app.domain.goals.service import contribute, goal_progress


async def nova_conta(t: Turn, p: ParsedIntent, space_id: UUID) -> str:
    if not p.amount_cents or p.amount_cents <= 0 or p.occurred_on is None:
        return (
            "Para anotar uma conta a pagar preciso do valor e do vencimento. "
            "Ex.: conta de internet 120 vence dia 10"
        )
    ctx = await t.context(space_id)
    category_id = await resolve_category(t, ctx, p, space_id, "expense")
    bill = await create_bill(
        t.session, actor_id=t.user_id, space_id=space_id, amount_cents=p.amount_cents,
        description=(p.description or p.merchant or "Conta")[:200], due_on=p.occurred_on,
        category_id=category_id,
    )  # fmt: skip
    return (
        f"📌 Anotei: {bill.description} · {format_brl(bill.amount_cents)} · "
        f"vence {bill.due_on:%d/%m}\nQuando pagar, é só mandar 'paguei'."
    )


async def aporte(t: Turn, p: ParsedIntent, space_id: UUID) -> str:
    return await run_aporte(t, Draft(action="aporte", p=p, space_id=space_id))


async def run_aporte(t: Turn, d: Draft) -> str:
    p = d.p
    if p.amount_cents is None or p.amount_cents <= 0:
        prefix = "" if p.amount_cents is None else ZERO + " "
        p.amount_cents = None
        return await ask(t, d, "amount", prefix + "Quanto você guardou? (ex.: 500)")
    ctx = await t.context(d.space_id)
    if not ctx.goals:
        return "Você ainda não tem metas. Crie uma no painel web (Metas)."
    best = resolve_hint(p.goal_hint, [g.name for g in ctx.goals])
    hint = fold(p.goal_hint or "")
    goals = [g for g in ctx.goals if g.name == best or (hint and hint in fold(g.name))]
    if len(goals) != 1:
        return "Qual meta? Suas metas: " + ", ".join(g.name for g in ctx.goals) + "."
    goal = goals[0]
    if d.payment is None:
        chosen, options = choose_account(ctx, [p.account_hint] if p.account_hint else [])
        if chosen is None:
            if not options:
                return NO_ACCOUNT
            d.options = options
            return await ask(
                t, d, "payment", options_text("De qual conta saiu?", [o.label for o in options])
            )
        d.payment = chosen
    tx = await contribute(
        t.session, actor_id=t.user_id, goal_id=goal.id, from_account_id=d.payment.id,
        amount_cents=p.amount_cents, on=t.today,
    )  # fmt: skip
    await tag_origin(t, tx.id)
    progress = await goal_progress(t.session, goal.id, today=t.today)
    return (
        f"✅ {format_brl(tx.amount_cents)} · Aporte na meta {goal.name} · hoje · "
        f"{d.payment.label}\n"
        f"Guardado: {format_brl(progress.saved)} de {format_brl(progress.target)}."
    )
