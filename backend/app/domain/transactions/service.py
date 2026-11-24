import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.access import use_account
from app.domain.accounts.models import Account
from app.domain.attachments import delete_unreferenced, remove_files
from app.domain.audit import audit
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
    await session.flush()
    audit(
        session,
        actor_id,
        "transaction.create",
        "transaction",
        tx.id,
        {"space_id": str(space_id), "type": type, "amount_cents": amount_cents},
    )
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


NO_MERCHANT = "Sem estabelecimento"
MERCHANT_LABEL = func.coalesce(func.nullif(func.trim(Transaction.merchant), ""), NO_MERCHANT)


@dataclass(frozen=True)
class Filters:
    start: date | None = None
    end: date | None = None
    category_id: UUID | None = None
    uncategorized: bool = False
    account_id: UUID | None = None
    card_id: UUID | None = None
    created_by: UUID | None = None
    type: str | None = None
    merchant: str | None = None  # rótulo (vazio aparece como NO_MERCHANT)
    effective: bool = False  # datas pela competência (cartão = vencimento da fatura)


def _filtered(space_id: UUID, f: Filters) -> Select[Any]:
    from app.domain.budgets.service import EFFECTIVE_ON  # evita import circular
    from app.domain.cards.models import Invoice

    day = EFFECTIVE_ON if f.effective else Transaction.occurred_on
    q = select(Transaction).where(Transaction.space_id == space_id)
    if f.effective:
        q = q.outerjoin(Invoice, Invoice.id == Transaction.invoice_id)
    if f.start is not None:
        q = q.where(day >= f.start)
    if f.end is not None:
        q = q.where(day <= f.end)
    if f.category_id is not None:
        q = q.where(Transaction.category_id == f.category_id)
    if f.uncategorized:
        q = q.where(Transaction.category_id.is_(None))
    if f.card_id is not None:
        q = q.where(Transaction.card_id == f.card_id)
    if f.created_by is not None:
        q = q.where(Transaction.created_by == f.created_by)
    if f.type is not None:
        q = q.where(Transaction.type == f.type)
    if f.merchant is not None:
        q = q.where(MERCHANT_LABEL == f.merchant)
    if f.account_id is not None:
        q = q.where(
            or_(
                Transaction.account_id == f.account_id,
                Transaction.counter_account_id == f.account_id,
            )
        )
    return q


async def list_transactions(
    session: AsyncSession, *, viewer_id: UUID, space_id: UUID, limit: int = 100, offset: int = 0,
    **filters: Any,
) -> list[Transaction]:  # fmt: skip
    """`filters`: campos de Filters."""
    await require_member(session, viewer_id, space_id)
    f = Filters(**filters)
    q = _filtered(space_id, f)
    day: Any = Transaction.occurred_on
    if f.effective:
        from app.domain.budgets.service import EFFECTIVE_ON

        day = EFFECTIVE_ON
    page = q.order_by(day.desc(), Transaction.created_at.desc())
    return list(await session.scalars(page.limit(limit).offset(offset)))


async def count_transactions(
    session: AsyncSession, *, viewer_id: UUID, space_id: UUID, **filters: Any
) -> int:
    await require_member(session, viewer_id, space_id)
    q = _filtered(space_id, Filters(**filters))
    return int(await session.scalar(select(func.count()).select_from(q.subquery())) or 0)


async def _target(
    session: AsyncSession, actor_id: UUID, tx_id: UUID
) -> tuple[Transaction, list[Transaction]]:
    """Lançamento que o autor pode alterar (é o autor ou dono do espaço) e o seu grupo de
    parcelas, ambos travados (delete+edit simultâneos se serializam)."""
    first = await session.get(Transaction, tx_id)
    if first is None:
        raise HTTPException(status_code=404, detail="not_found")
    member = await require_member(session, actor_id, first.space_id)  # não membro = 404
    if first.created_by != actor_id and member.role != "owner":
        raise HTTPException(status_code=403, detail="edit_forbidden")
    where = (
        Transaction.installment_group_id == first.installment_group_id
        if first.installment_group_id is not None
        else Transaction.id == tx_id
    )
    rows = list(  # mesma ordem em todo mundo: sem deadlock entre parcelas do mesmo grupo
        await session.scalars(
            select(Transaction)
            .where(where)
            .order_by(Transaction.installment_number, Transaction.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    tx = next((t for t in rows if t.id == tx_id), None)
    if tx is None:  # apagado por outra transação enquanto esperávamos o lock
        raise HTTPException(status_code=404, detail="not_found")
    return tx, rows


async def update_transaction(
    session: AsyncSession, *, actor_id: UUID, tx_id: UUID, amount_cents: int | None = None,
    description: str | None = None, merchant: str | None = None,
    category_id: UUID | None = None, occurred_on: date | None = None,
) -> Transaction:  # fmt: skip
    """Corrige um lançamento (None = não muda). Só despesa/receita: pagamentos e aportes têm
    fluxo próprio (só podem ser apagados). Parcelado: só categoria/descrição/estabelecimento,
    no grupo todo."""
    from app.domain.cards.models import Invoice
    from app.domain.cards.service import sync_invoice_bill

    tx, group = await _target(session, actor_id, tx_id)
    if tx.type == "transfer" or tx.bill_id is not None or tx.goal_id is not None:
        raise DomainError("not_editable")
    if tx.installment_group_id is not None and (amount_cents is not None or occurred_on):
        raise DomainError("installment_group_not_editable")
    if tx.card_id is not None and occurred_on is not None:
        raise DomainError("card_date_not_editable")  # mudaria a fatura: apague e lance de novo
    await check_common(
        session, actor_id=actor_id, space_id=tx.space_id, type=tx.type,
        amount_cents=tx.amount_cents if amount_cents is None else amount_cents,
        category_id=tx.category_id if category_id is None else category_id,
        occurred_on=occurred_on or tx.occurred_on,
    )  # fmt: skip
    before = {"amount_cents": tx.amount_cents, "category_id": str(tx.category_id)}
    for t in group:
        if amount_cents is not None:
            t.amount_cents = amount_cents
        if description is not None:
            t.description = description
        if merchant is not None:
            t.merchant = merchant
        if category_id is not None:
            t.category_id = category_id
        if occurred_on is not None:
            t.occurred_on = occurred_on
    await session.flush()
    if tx.invoice_id is not None and amount_cents is not None:
        invoice = await session.get(Invoice, tx.invoice_id)
        assert invoice is not None
        await sync_invoice_bill(session, invoice)  # conta espelho = total da fatura
    audit(
        session, actor_id, "transaction.update", "transaction", tx.id,
        {"space_id": str(tx.space_id), "before": before,
         "after": {"amount_cents": tx.amount_cents, "category_id": str(tx.category_id)}},
    )  # fmt: skip
    await session.commit()
    return tx


async def delete_transaction(
    session: AsyncSession, *, actor_id: UUID, tx_id: UUID
) -> list[Transaction]:
    """Apaga o lançamento (compra parcelada: o grupo inteiro) e reajusta fatura, conta a pagar
    (pagamento desfeito reabre) e meta (aporte que deixaria a meta negativa é recusado)."""
    from app.domain.bills.models import Bill
    from app.domain.bills.status import refresh_status
    from app.domain.cards.models import Invoice
    from app.domain.cards.service import sync_invoice_bill
    from app.domain.goals.models import Goal
    from app.domain.goals.service import goal_saved

    tx, victims = await _target(session, actor_id, tx_id)
    invoice_ids = {t.invoice_id for t in victims if t.invoice_id is not None}
    bill_ids = {t.bill_id for t in victims if t.bill_id is not None and t.invoice_id is None}
    goal_ids = {t.goal_id for t in victims if t.goal_id is not None}
    for goal_id in goal_ids:
        await session.get(Goal, goal_id, with_for_update=True)  # serializa com retiradas
    attachment_ids = {t.attachment_id for t in victims if t.attachment_id is not None}
    for t in victims:
        await session.delete(t)
    await session.flush()
    for goal_id in goal_ids:
        if await goal_saved(session, goal_id) < 0:
            await session.rollback()
            raise DomainError("insufficient_saved")  # há retiradas que dependem deste aporte
    for invoice_id in invoice_ids:  # compra apagada ou pagamento desfeito: total e status
        invoice = await session.get(Invoice, invoice_id)
        if invoice is not None:
            await sync_invoice_bill(session, invoice)
    for bill_id in bill_ids:  # pagamento de conta a pagar desfeito: reabre
        bill = await session.get(Bill, bill_id, with_for_update=True)
        if bill is not None:
            await refresh_status(session, bill)
    audit(
        session, actor_id, "transaction.delete", "transaction", tx.id,
        {"space_id": str(tx.space_id), "count": len(victims),
         "amount_cents": sum(t.amount_cents for t in victims)},
    )  # fmt: skip
    paths = await delete_unreferenced(session, attachment_ids)
    await session.commit()
    remove_files(paths)
    return victims
