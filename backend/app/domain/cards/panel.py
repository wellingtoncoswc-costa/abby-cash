from collections import defaultdict
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.serialize import row
from app.domain.cards.models import Invoice
from app.domain.cards.service import invoice_statement, invoice_summary, visible_card


async def card_panel(
    session: AsyncSession, viewer_id: UUID, card_id: UUID, *, today: date,
    invoice_id: UUID | None = None,
) -> dict[str, Any]:  # fmt: skip
    """Resumo e gastos do cartão. Compras de espaços de que o visualizador não é membro entram só
    em `private_total_cents` (nunca por categoria nem na lista de maiores).
    # ponytail: olha as 24 faturas mais recentes (igual à listagem); paginar se passar disso
    """
    card = await visible_card(session, viewer_id, card_id)
    invs = list(
        await session.scalars(
            select(Invoice)
            .where(Invoice.card_id == card.id)
            .order_by(Invoice.closing_on.desc())
            .limit(24)
        )
    )
    sums = {i.id: await invoice_summary(session, i) for i in invs}
    used = sum(s["remaining_cents"] for s in sums.values())
    if invoice_id is not None:
        sel = next((i for i in invs if i.id == invoice_id), None)
        if sel is None:
            raise HTTPException(status_code=404, detail="not_found")
    else:  # a que ainda vai fechar (a mais próxima) ou, sem nenhuma, a mais recente
        sel = next((i for i in reversed(invs) if i.closing_on >= today), invs[0] if invs else None)
    by_cat: dict[UUID | None, int] = defaultdict(int)
    top: list[dict[str, Any]] = []
    private = 0
    if sel is not None:
        stmt = await invoice_statement(session, viewer_id, sel.id)
        private = stmt.private_total_cents
        for it in stmt.items:
            by_cat[it.category_id] += it.amount_cents
        top = [
            {"description": it.description, "merchant": it.merchant,
             "amount_cents": it.amount_cents, "occurred_on": it.occurred_on}
            for it in sorted(stmt.items, key=lambda x: -x.amount_cents)[:5]
        ]  # fmt: skip
    return {
        "invoice": row(sel) | sums[sel.id] if sel else None,
        "limit_cents": card.limit_cents,
        "used_cents": used,
        "available_cents": None if card.limit_cents is None else card.limit_cents - used,
        "by_category": [
            {"category_id": k, "total_cents": v}
            for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])
        ],
        "private_total_cents": private,
        "top": top,
        "history": [
            {
                "invoice_id": i.id,
                "closing_on": i.closing_on,
                "due_on": i.due_on,
                "total_cents": sums[i.id]["total_cents"],
            }
            for i in sorted(invs[:6], key=lambda i: i.closing_on)
        ],  # fmt: skip
    }
