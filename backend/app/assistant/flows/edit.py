import re
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.assistant.amounts import ZERO_OR_NEG, parse_bare_amount
from app.assistant.hints import resolve_date
from app.assistant.intents import ParsedIntent
from app.assistant.replies import CORRECT_PROMPT, tx_line
from app.assistant.resolve import resolve_hint
from app.assistant.state import set_state
from app.assistant.turn import Turn
from app.core.money import format_brl
from app.core.text import fold
from app.domain.categories.models import Category, CategoryRule
from app.domain.transactions.models import Transaction
from app.domain.transactions.service import (
    delete_transaction,
    normalize_merchant,
    update_transaction,
)

_CORRECTION = re.compile(r"\s*(valor|categoria|descri[cç][aã]o|data)\s+(.+)", re.I | re.S)
NOT_FOUND = "Não achei nenhum lançamento seu feito pelo chat para {}."


async def last_tx(t: Turn) -> Transaction | None:
    """Último lançamento feito POR ESTE USUÁRIO neste canal (nunca o do web nem de outra pessoa)."""
    return await t.session.scalar(
        select(Transaction)
        .where(Transaction.created_by == t.user_id, Transaction.origin == t.channel)
        .order_by(Transaction.created_at.desc(), Transaction.installment_number.asc().nulls_last())
        .limit(1)
    )


def parse_correction(text: str, today: date) -> dict[str, Any] | None:
    """ "valor 50", "categoria Lazer", "descrição cinema", "data ontem" -> campos a mudar."""
    m = _CORRECTION.fullmatch(text)
    if m is None:
        return None
    key, rest = fold(m.group(1)), m.group(2).strip()
    if key == "valor":
        cents = parse_bare_amount(rest)
        if cents is None and ZERO_OR_NEG.fullmatch(rest):
            return {"amount_cents": 0}  # o domínio recusa e a pessoa recebe o aviso
        return {"amount_cents": cents} if cents else None
    if key == "categoria":
        return {"category_name": rest}
    if key == "data":
        day = resolve_date(rest, today)
        return {"occurred_on": day} if day else None
    return {"description": rest[:500]}


async def learn_rule(t: Turn, space_id: UUID, label: str, category_id: UUID) -> None:
    """Corrigiu a categoria: aquele estabelecimento passa a ir sempre para ela."""
    norm = normalize_merchant(label)
    if not norm:
        return
    await t.session.execute(
        insert(CategoryRule)
        .values(space_id=space_id, merchant_norm=norm, category_id=category_id)
        .on_conflict_do_update(
            constraint="uq_category_rules_space_merchant", set_={"category_id": category_id}
        )
    )
    await t.session.commit()


async def apply_correction(t: Turn, fields: dict[str, Any]) -> str:
    tx = await last_tx(t)
    if tx is None:
        return NOT_FOUND.format("corrigir")
    category_id: UUID | None = None
    if name := fields.get("category_name"):
        kind = "income" if tx.type == "income" else "expense"
        cats = await t.session.scalars(
            select(Category).where(Category.space_id == tx.space_id, Category.kind == kind)
        )
        by_name = {c.name: c for c in cats}
        best = resolve_hint(name, list(by_name))  # sem acento/caixa; aproximado
        if best is None:
            return f"Não achei a categoria {name}. Opções: " + ", ".join(by_name)
        category_id = by_name[best].id
    space_id, label = tx.space_id, tx.merchant or tx.description
    out = await update_transaction(
        t.session, actor_id=t.user_id, tx_id=tx.id, amount_cents=fields.get("amount_cents"),
        category_id=category_id, description=fields.get("description"),
        occurred_on=fields.get("occurred_on"),
    )  # fmt: skip
    if category_id is not None:
        await learn_rule(t, space_id, label or "", category_id)
    return "✏️ Corrigi:\n" + await tx_line(t.session, out, t.today)


async def corrigir(t: Turn, p: ParsedIntent, space_id: UUID) -> str:
    name = None
    if p.category_index is not None:
        ctx = await t.context(space_id)  # o nº é da lista do prompt deste espaço
        if 1 <= p.category_index <= len(ctx.categories):
            name = ctx.categories[p.category_index - 1].name
    fields: dict[str, Any] = {
        "amount_cents": p.amount_cents, "category_name": name, "description": p.description,
        "occurred_on": p.occurred_on,
    }  # fmt: skip
    fields = {k: v for k, v in fields.items() if v is not None}
    if not fields:
        await set_state(t.session, t.user_id, t.channel, "correct", {}, t.now)
        return CORRECT_PROMPT
    return await apply_correction(t, fields)


async def _group(t: Turn, tx: Transaction) -> list[Transaction]:
    if tx.installment_group_id is None:
        return [tx]
    rows = await t.session.scalars(
        select(Transaction).where(Transaction.installment_group_id == tx.installment_group_id)
    )
    return list(rows)


async def apagar(t: Turn) -> str:
    """Pede confirmação (decisão do dono): só um "sim" explícito apaga (ver `confirm_delete`)."""
    tx = await last_tx(t)
    if tx is None:
        return NOT_FOUND.format("apagar")
    group = await _group(t, tx)
    what = tx.merchant or tx.description or "lançamento"
    extra = f" ({len(group)} parcelas)" if len(group) > 1 else ""
    total = sum(g.amount_cents for g in group)
    await set_state(t.session, t.user_id, t.channel, "delete", {"tx_id": str(tx.id)}, t.now)
    return f"Apagar {format_brl(total)} · {what}{extra}? Responda sim ou não"


async def confirm_delete(t: Turn, tx_id: UUID) -> str:
    tx = await t.session.get(Transaction, tx_id)
    if tx is None:
        return "Não encontrei isso, ou você não tem acesso."
    line = (await tx_line(t.session, tx, t.today, hint=False)).removeprefix("✅ ")
    deleted = await delete_transaction(t.session, actor_id=t.user_id, tx_id=tx_id)
    extra = f" ({len(deleted)} parcelas)" if len(deleted) > 1 else ""
    return f"🗑️ Apaguei: {line}{extra}"
