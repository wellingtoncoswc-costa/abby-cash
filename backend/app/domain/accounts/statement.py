from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.access import visible_account
from app.domain.spaces.models import SpaceMember
from app.domain.transactions.models import Transaction
from app.domain.transactions.rules import signed


@dataclass(frozen=True)
class TransactionView:
    id: UUID
    space_id: UUID
    type: str
    amount_cents: int  # com o sinal da conta
    occurred_on: date
    description: str
    merchant: str | None
    category_id: UUID | None
    created_by: UUID | None


@dataclass(frozen=True)
class Statement:
    items: list[TransactionView]
    private_total_cents: int  # soma dos itens de espaços de que o visualizador NÃO é membro
    total_cents: int  # itens + privados


async def build_statement(
    session: AsyncSession, viewer_id: UUID, rows: Sequence[tuple[Transaction, int]]
) -> Statement:
    """Itens de espaços do visualizador viram itens; o resto é só somado."""
    mine = set(
        await session.scalars(select(SpaceMember.space_id).where(SpaceMember.user_id == viewer_id))
    )
    items: list[TransactionView] = []
    private = 0
    for tx, amount in rows:
        if tx.space_id in mine:
            items.append(
                TransactionView(
                    tx.id,
                    tx.space_id,
                    tx.type,
                    amount,
                    tx.occurred_on,
                    tx.description,
                    tx.merchant,
                    tx.category_id,
                    tx.created_by,
                )  # fmt: skip
            )
        else:
            private += amount
    return Statement(items, private, sum(i.amount_cents for i in items) + private)


async def account_statement(
    session: AsyncSession, viewer_id: UUID, account_id: UUID, start: date, end: date
) -> Statement:
    acc = await visible_account(session, viewer_id, account_id)  # 404 se não for membro do dono
    txs = await session.scalars(
        select(Transaction)
        .where(
            or_(Transaction.account_id == acc.id, Transaction.counter_account_id == acc.id),
            Transaction.occurred_on >= start,
            Transaction.occurred_on <= end,
        )
        .order_by(Transaction.occurred_on, Transaction.created_at)
    )
    return await build_statement(session, viewer_id, [(t, signed(t, acc.id)) for t in txs])
