from datetime import date, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Select, func, select

from app.assistant.intents import ParsedIntent
from app.assistant.replies import month_name
from app.assistant.resolve import pick_category
from app.assistant.turn import Turn
from app.core.dates import add_months
from app.core.money import format_brl
from app.domain.accounts.models import Account
from app.domain.bills.models import Bill
from app.domain.budgets.service import budget_overview
from app.domain.cards.models import CreditCard, Invoice
from app.domain.cards.service import invoice_statement, invoice_summary
from app.domain.categories.models import Category
from app.domain.spaces.access import require_member
from app.domain.spaces.models import Space, SpaceMember
from app.domain.transactions.models import Transaction
from app.domain.transactions.service import account_balance

# Toda consulta parte do espaço-alvo (já checado com require_member) ou dos espaços de que o
# usuário é membro: o que está em espaço alheio (ex.: #pessoal de outro membro) nunca entra.


def period_bounds(period: str, today: date) -> tuple[date, date, str]:
    first = today.replace(day=1)
    if period == "hoje":
        return today, today, "hoje"
    if period == "ontem":
        return today - timedelta(days=1), today - timedelta(days=1), "ontem"
    if period == "semana":
        return today - timedelta(days=6), today, "nos últimos 7 dias"
    if period == "mes_passado":
        prev = add_months(first, -1)
        return prev, first - timedelta(days=1), f"em {month_name(prev)}"
    return first, today, f"em {month_name(today)}"


def _member_spaces(t: Turn) -> Select[Any]:
    return select(SpaceMember.space_id).where(SpaceMember.user_id == t.user_id)


async def gastos(t: Turn, p: ParsedIntent, space_id: UUID) -> str:
    """Soma por data da compra (`occurred_on`), inclusive no cartão."""
    await require_member(t.session, t.user_id, space_id)
    ctx = await t.context(space_id)
    start, end, label = period_bounds(p.period or "mes", t.today)
    cats = {c.id: c.name for c in ctx.categories if c.kind == "expense"}
    q = select(Transaction.category_id, func.sum(Transaction.amount_cents)).where(
        Transaction.space_id == space_id, Transaction.type == "expense",
        Transaction.occurred_on >= start, Transaction.occurred_on <= end,
    )  # fmt: skip
    if p.category_index is not None:
        wanted = pick_category(ctx, "expense", p.category_index)
        if wanted is None:
            return "Não achei essa categoria."
        q = q.where(Transaction.category_id == wanted.id)
    rows = (await t.session.execute(q.group_by(Transaction.category_id))).all()
    space = await t.session.get(Space, space_id)
    where = f" — {space.name}" if space else ""
    if not rows:
        return f"Nenhum gasto {label}{where}."
    total = sum(int(v) for _, v in rows)
    head = f"📊 Gastos {label}: {format_brl(total)}{where}"
    if p.category_index is not None:
        return head
    top = sorted(rows, key=lambda r: -int(r[1]))[:5]
    lines = [
        f"• {cats.get(c, 'Sem categoria') if c else 'Sem categoria'}: {format_brl(int(v))}"
        for c, v in top
    ]
    return head + "\n" + "\n".join(lines)


async def saldo(t: Turn) -> str:
    accounts = list(
        await t.session.scalars(
            select(Account).where(Account.space_id.in_(_member_spaces(t))).order_by(Account.name)
        )
    )
    if not accounts:
        return "Você ainda não tem contas cadastradas."
    balances = [(a.name, await account_balance(t.session, a.id)) for a in accounts]
    lines = [f"• {name}: {format_brl(cents)}" for name, cents in balances]
    return "💰 Saldos:\n" + "\n".join(lines) + f"\nTotal: {format_brl(sum(c for _, c in balances))}"


async def teto(t: Turn, space_id: UUID) -> str:
    await require_member(t.session, t.user_id, space_id)
    month = t.today.replace(day=1)
    try:
        ov = await budget_overview(t.session, viewer_id=t.user_id, space_id=space_id, month=month)
    except HTTPException:  # 404: sem teto definido (a participação já foi checada acima)
        return f"Você ainda não definiu um teto para {month_name(month)}. Defina no painel web."
    limit, spent = ov["limit_cents"], ov["spent_cents"]
    lines = [
        f"🎯 Teto de {month_name(month)}: {format_brl(spent)} de {format_brl(limit)} "
        f"({spent * 100 // limit}%)."
    ]
    names = {
        c.id: c.name
        for c in await t.session.scalars(select(Category).where(Category.space_id == space_id))
    }
    for c in ov["categories"]:
        name = names.get(c["category_id"], "?")
        lines.append(f"• {name}: {format_brl(c['spent_cents'])} de {format_brl(c['limit_cents'])}")
    return "\n".join(lines)


async def faturas(t: Turn) -> str:
    rows = (
        await t.session.execute(
            select(Invoice, CreditCard)
            .join(CreditCard, CreditCard.id == Invoice.card_id)
            .join(Bill, Bill.invoice_id == Invoice.id)
            .where(
                CreditCard.space_id.in_(_member_spaces(t)),
                Bill.status != "paid", Bill.amount_cents > 0,
            )
            .order_by(Invoice.due_on)
            .limit(5)
        )
    ).all()  # fmt: skip
    if not rows:
        return "Nenhuma fatura em aberto."
    lines = []
    for inv, card in rows:
        s = await invoice_summary(t.session, inv)
        open_ = format_brl(s["remaining_cents"])
        line = f"💳 {card.name} · vence {inv.due_on:%d/%m}: {open_} em aberto"
        if s["paid_cents"]:
            line += f" (total {format_brl(s['total_cents'])})"
        private = (await invoice_statement(t.session, t.user_id, inv.id)).private_total_cents
        if private:  # compras de espaços alheios: só o total agregado (spec 14.1)
            line += f" · Outros lançamentos (privados): {format_brl(private)}"
        lines.append(line)
    return "\n".join(lines)
