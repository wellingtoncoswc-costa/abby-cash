import re
import unicodedata
from datetime import date
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.access import use_account
from app.domain.accounts.models import Account
from app.domain.errors import DomainError
from app.domain.spaces.access import require_member
from app.domain.transactions.models import Transaction
from app.domain.transactions.rules import check_common, signed

TYPES = {"expense", "income", "transfer"}
_STORE_NO = re.compile(r"\b(?:n[oº°]?|loja|filial|unid(?:ade)?)\.?\s*\d+\b")


def normalize_merchant(text: str) -> str:
    """minúsculas, sem acento, sem número de loja/dígitos/símbolos, espaços colapsados."""
    s = unicodedata.normalize("NFKD", text.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _STORE_NO.sub(" ", s)
    return " ".join(re.sub(r"[^a-z\s]", " ", s).split())


async def create_transaction(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, type: str, amount_cents: int,
    occurred_on: date, description: str = "", merchant: str | None = None,
    category_id: UUID | None = None, account_id: UUID | None = None,
    counter_account_id: UUID | None = None, card_id: UUID | None = None, origin: str = "web",
    source_message_id: str | None = None, attachment_id: UUID | None = None,
) -> Transaction:  # fmt: skip
    if type not in TYPES:
        raise DomainError("invalid_type")
    if card_id is not None:  # compra no cartão: fatura e parcelas ficam no serviço de cartões
        if type != "expense" or account_id is not None or counter_account_id is not None:
            raise DomainError("invalid_card_purchase")
        from app.domain.cards.service import register_card_purchase  # evita import circular

        purchase = await register_card_purchase(
            session, actor_id=actor_id, space_id=space_id, card_id=card_id,
            amount_cents=amount_cents, occurred_on=occurred_on, description=description,
            merchant=merchant, category_id=category_id, origin=origin,
            source_message_id=source_message_id, attachment_id=attachment_id,
        )  # fmt: skip
        return purchase[0]
    await check_common(
        session, actor_id=actor_id, space_id=space_id, type=type, amount_cents=amount_cents,
        category_id=category_id, occurred_on=occurred_on,
    )  # fmt: skip
    if account_id is None:
        raise DomainError("account_required")
    await use_account(session, actor_id, account_id)
    if type == "transfer":
        if counter_account_id is None or counter_account_id == account_id:
            raise DomainError("invalid_transfer")
        await use_account(session, actor_id, counter_account_id)
    elif counter_account_id is not None:
        raise DomainError("invalid_transfer")
    tx = Transaction(
        space_id=space_id, type=type, amount_cents=amount_cents, occurred_on=occurred_on,
        description=description, merchant=merchant, category_id=category_id,
        account_id=account_id, counter_account_id=counter_account_id, created_by=actor_id,
        origin=origin, source_message_id=source_message_id, attachment_id=attachment_id,
    )  # fmt: skip
    session.add(tx)
    await session.commit()
    return tx


async def account_balance(session: AsyncSession, account_id: UUID) -> int:
    """saldo inicial + receitas − despesas à vista − transferências de saída + de entrada."""
    acc = await session.get(Account, account_id)
    if acc is None:
        raise DomainError("account_not_found")
    rows = await session.scalars(
        select(Transaction).where(
            or_(Transaction.account_id == account_id, Transaction.counter_account_id == account_id)
        )
    )
    # ponytail: soma em Python; usar SUM(CASE ...) no SQL se passar de ~10k lançamentos
    return acc.initial_balance_cents + sum(signed(t, account_id) for t in rows)


async def list_transactions(
    session: AsyncSession, *, viewer_id: UUID, space_id: UUID, start: date | None = None,
    end: date | None = None, category_id: UUID | None = None, account_id: UUID | None = None,
    limit: int = 100, offset: int = 0,
) -> list[Transaction]:  # fmt: skip
    await require_member(session, viewer_id, space_id)
    q = select(Transaction).where(Transaction.space_id == space_id)
    if start is not None:
        q = q.where(Transaction.occurred_on >= start)
    if end is not None:
        q = q.where(Transaction.occurred_on <= end)
    if category_id is not None:
        q = q.where(Transaction.category_id == category_id)
    if account_id is not None:
        q = q.where(
            or_(Transaction.account_id == account_id, Transaction.counter_account_id == account_id)
        )
    q = q.order_by(Transaction.occurred_on.desc(), Transaction.created_at.desc())
    return list(await session.scalars(q.limit(limit).offset(offset)))
