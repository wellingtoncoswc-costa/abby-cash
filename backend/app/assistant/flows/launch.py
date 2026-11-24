import logging
from datetime import date
from uuid import UUID

from sqlalchemy import select

from app.assistant.context import SpaceContext
from app.assistant.flows.common import ask
from app.assistant.flows.payment import choose_payment
from app.assistant.hints import Hints
from app.assistant.intents import ParsedIntent
from app.assistant.notify import notify_members
from app.assistant.replies import (
    FUTURE_DATE,
    NO_ACCOUNT,
    NO_CARD,
    ZERO,
    alert_text,
    future_impact_text,
    options_text,
    tx_line,
)
from app.assistant.resolve import pick_category
from app.assistant.turn import Draft, Turn
from app.core.money import format_brl
from app.domain.budgets.service import evaluate_thresholds, future_impact
from app.domain.cards.service import register_card_purchase
from app.domain.categories.models import Category, CategoryRule
from app.domain.transactions.models import Transaction
from app.domain.transactions.service import create_transaction, normalize_merchant

CONFIDENCE_MIN = 0.6
log = logging.getLogger(__name__)


async def start(t: Turn, p: ParsedIntent, space_id: UUID, h: Hints, warn: str | None) -> str:
    return await run(
        t, Draft(action="launch", p=p, space_id=space_id, warn=warn, private=h.private)
    )


async def resolve_category(
    t: Turn, ctx: SpaceContext, p: ParsedIntent, space_id: UUID, kind: str
) -> UUID | None:
    """Regra aprendida > categoria sugerida pelo nº da lista (do próprio espaço) > "Outros"."""
    ids = {c.id for c in ctx.categories if c.kind == kind}
    norm = normalize_merchant(p.merchant or p.description or "")
    if norm:
        learned = await t.session.scalar(
            select(CategoryRule.category_id).where(
                CategoryRule.space_id == space_id, CategoryRule.merchant_norm == norm
            )
        )
        if learned in ids:
            return learned
    if cat := pick_category(ctx, kind, p.category_index):
        return cat.id
    return next((c.id for c in ctx.categories if c.kind == kind and c.name == "Outros"), None)


async def budget_notes(
    t: Turn, space_id: UUID, txs: list[Transaction], each_cents: int
) -> tuple[list[str], list[str]]:
    """(frase de impacto futuro, alertas de teto) de uma despesa recém-gravada."""
    impact = await future_impact(t.session, space_id, txs)  # meses de vencimento das faturas
    months = {f.month for f in impact} | {
        tx.occurred_on.replace(day=1) for tx in txs if tx.card_id is None
    }
    notes: list[str] = []
    if len(txs) > 1 and (with_limit := [f.month for f in impact if f.limit is not None]):
        notes.append(future_impact_text(each_cents, with_limit))
    alerts: list[str] = []
    for month in sorted(months):
        for a in await evaluate_thresholds(t.session, space_id, month):
            cat = None
            if a.category_id is not None:
                cat = await t.session.scalar(
                    select(Category.name).where(Category.id == a.category_id)
                )
            alerts.append(alert_text(a, month, cat))
    return notes, alerts


async def run(t: Turn, d: Draft) -> str:
    """Lança a despesa/receita ou faz a próxima pergunta que falta (valor, confiança, conta)."""
    p = d.p
    if p.amount_cents is None or p.amount_cents <= 0:
        prefix = "" if p.amount_cents is None else ZERO + " "
        p.amount_cents = None
        return await ask(t, d, "amount", prefix + "Quanto foi? (ex.: 45 ou 45,50)")
    if p.confidence < CONFIDENCE_MIN and not d.confirmed:
        what = p.description or p.merchant or "isso"
        text = f'Entendi {format_brl(p.amount_cents)} em "{what}". Posso lançar? (sim/não)'
        return await ask(t, d, "confirm", text)
    ctx = await t.context(d.space_id)
    income = p.intent == "lancar_receita"
    if d.payment is None:
        chosen, options = choose_payment(ctx, p, income=income)
        if chosen is None:
            if not options:
                return NO_CARD if (p.installments or 1) > 1 or p.card_hint else NO_ACCOUNT
            d.options = options
            question = "Em qual cartão foi?" if options[0].type == "card" else "Em qual conta foi?"
            return await ask(t, d, "payment", options_text(question, [o.label for o in options]))
        d.payment = chosen
    occurred: date = p.occurred_on or t.today
    if occurred > t.today:
        return FUTURE_DATE
    n = p.installments if p.installments and p.installments > 1 and not income else 1
    category_id = await resolve_category(t, ctx, p, d.space_id, "income" if income else "expense")
    description = (p.description or p.merchant or "")[:500]
    merchant = p.merchant[:200] if p.merchant else None
    if d.payment.type == "card":
        txs = await register_card_purchase(
            t.session, actor_id=t.user_id, space_id=d.space_id, card_id=d.payment.id,
            amount_cents=p.amount_cents, occurred_on=occurred, installments=n,
            description=description, merchant=merchant, category_id=category_id,
            origin=t.channel, source_message_id=t.message_id, attachment_id=d.attachment_id,
        )  # fmt: skip
    else:
        txs = [
            await create_transaction(
                t.session,
                actor_id=t.user_id,
                space_id=d.space_id,
                type="income" if income else "expense",
                amount_cents=p.amount_cents,
                occurred_on=occurred,
                description=description,
                merchant=merchant,
                category_id=category_id,
                account_id=d.payment.id,
                origin=t.channel,
                source_message_id=t.message_id,
                attachment_id=d.attachment_id,
            )  # fmt: skip
        ]
    line = await tx_line(
        t.session, txs[0], t.today, total_cents=p.amount_cents if n > 1 else None,
        installments=n if n > 1 else None, private=d.private,
    )  # fmt: skip
    lines = [d.warn, line] if d.warn else [line]
    if not income:
        try:  # o lançamento já foi gravado: falha em alerta nunca vira "falhou"
            notes, alerts = await budget_notes(t, d.space_id, txs, txs[-1].amount_cents)
            lines += notes + alerts
            for text in alerts:  # o teto é do espaço: os outros membros também precisam saber
                await notify_members(t.session, d.space_id, t.user_id, text)
        except Exception as e:
            log.warning("budget alerts failed (%s)", type(e).__name__)
            await t.session.rollback()
    return "\n".join(lines)
