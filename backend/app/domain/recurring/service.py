from datetime import date, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import add_months
from app.domain.accounts.access import use_account
from app.domain.accounts.models import Account
from app.domain.audit import audit
from app.domain.bills.recurrence import Recurrence, generate_occurrences
from app.domain.errors import DomainError
from app.domain.loans.models import Loan
from app.domain.loans.service import list_installments
from app.domain.recurring.models import RecurringItem, RecurringPosting
from app.domain.spaces.access import require_member, require_owner
from app.domain.transactions.rules import check_common
from app.domain.transactions.service import account_balance, create_transaction

PROJECTION_MONTHS = 6


def occurrences(item: RecurringItem, start: date, end: date) -> list[date]:
    """Datas do fixo em [start, end], respeitando início e fim do item."""
    lo = max(start, item.starts_on)
    hi = min(end, item.ends_on) if item.ends_on else end
    if lo > hi:
        return []
    months = (hi.year - lo.year) * 12 + hi.month - lo.month + 1
    return [d for d in generate_occurrences(Recurrence.from_json(item.rule), lo, months) if d <= hi]


def next_due(item: RecurringItem, today: date) -> date | None:
    """Próxima data (>= hoje) do fixo ativo; olha 13 meses à frente (cobre o anual)."""
    if not item.active:
        return None
    lo = max(today, item.starts_on)
    nxt = occurrences(item, lo, add_months(lo, 13))
    return nxt[0] if nxt else None


async def _same_space_account(
    session: AsyncSession, actor_id: UUID, space_id: UUID, account_id: UUID
) -> None:
    acc = await use_account(session, actor_id, account_id)
    if acc.space_id != space_id:
        raise HTTPException(status_code=404, detail="account_not_found")


async def visible_item(
    session: AsyncSession, viewer_id: UUID, space_id: UUID, item_id: UUID
) -> RecurringItem:
    item = await session.get(RecurringItem, item_id)
    if item is None or item.space_id != space_id:
        raise HTTPException(status_code=404, detail="not_found")
    await require_member(session, viewer_id, space_id)
    return item


async def create_item(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, type: str, description: str,
    amount_cents: int, account_id: UUID, rule: Recurrence, starts_on: date,
    ends_on: date | None = None, category_id: UUID | None = None,
) -> RecurringItem:  # fmt: skip
    await require_owner(session, actor_id, space_id)
    await _same_space_account(session, actor_id, space_id, account_id)
    if ends_on is not None and ends_on < starts_on:
        raise DomainError("invalid_period")
    await check_common(
        session, actor_id=actor_id, space_id=space_id, type=type, amount_cents=amount_cents,
        category_id=category_id, occurred_on=starts_on,
    )  # fmt: skip
    item = RecurringItem(
        space_id=space_id, type=type, description=description, amount_cents=amount_cents,
        account_id=account_id, category_id=category_id, rule=rule.to_json(), starts_on=starts_on,
        ends_on=ends_on, created_by=actor_id,
    )  # fmt: skip
    session.add(item)
    await session.flush()
    audit(session, actor_id, "recurring.create", "recurring_item", item.id,
          {"space_id": str(space_id), "type": type, "amount_cents": amount_cents})  # fmt: skip
    await session.commit()
    return item


async def update_item(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, item_id: UUID, fields: dict[str, Any]
) -> RecurringItem:
    """fields: description, amount_cents, account_id, category_id, rule (Recurrence), ends_on,
    active. Vale dos próximos lançamentos em diante; o que já foi lançado não muda."""
    await require_owner(session, actor_id, space_id)
    item = await visible_item(session, actor_id, space_id, item_id)
    if "account_id" in fields:
        await _same_space_account(session, actor_id, space_id, fields["account_id"])
    if "rule" in fields:
        fields = {**fields, "rule": fields["rule"].to_json()}
    for k, v in fields.items():
        setattr(item, k, v)
    if item.ends_on is not None and item.ends_on < item.starts_on:
        await session.rollback()
        raise DomainError("invalid_period")
    await check_common(
        session, actor_id=actor_id, space_id=space_id, type=item.type,
        amount_cents=item.amount_cents, category_id=item.category_id, occurred_on=item.starts_on,
    )  # fmt: skip
    audit(session, actor_id, "recurring.update", "recurring_item", item.id,
          {"space_id": str(space_id), "fields": sorted(fields)})  # fmt: skip
    await session.commit()
    return item


async def delete_item(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, item_id: UUID
) -> None:
    await require_owner(session, actor_id, space_id)
    item = await visible_item(session, actor_id, space_id, item_id)
    audit(session, actor_id, "recurring.delete", "recurring_item", item.id,
          {"space_id": str(space_id)})  # fmt: skip
    await session.delete(item)  # lançamentos já feitos ficam; postings somem em cascata
    await session.commit()


async def list_items(
    session: AsyncSession, *, viewer_id: UUID, space_id: UUID, today: date
) -> list[dict[str, Any]]:
    await require_member(session, viewer_id, space_id)
    rows = await session.scalars(
        select(RecurringItem)
        .where(RecurringItem.space_id == space_id)
        .order_by(RecurringItem.type.desc(), RecurringItem.description)
    )
    return [{"item": i, "next_due_on": next_due(i, today)} for i in rows]


async def post_due(session: AsyncSession, item: RecurringItem, today: date) -> int:
    """Lança as datas devidas (<= hoje) ainda sem posting. Idempotente: o posting entra antes e
    é desfeito se o lançamento falhar, então a data é tentada de novo no próximo ciclo."""
    done = set(
        await session.scalars(
            select(RecurringPosting.due_on).where(RecurringPosting.item_id == item.id)
        )
    )
    n = 0
    for d in occurrences(item, item.starts_on, today):
        if d in done:
            continue
        claimed = await session.scalar(
            insert(RecurringPosting)
            .values(item_id=item.id, due_on=d)
            .on_conflict_do_nothing()
            .returning(RecurringPosting.due_on)
        )
        await session.commit()
        if claimed is None:  # outra execução pegou esta data
            continue
        try:
            tx = await create_transaction(
                session, actor_id=item.created_by, space_id=item.space_id, type=item.type,
                amount_cents=item.amount_cents, occurred_on=d, description=item.description,
                category_id=item.category_id, account_id=item.account_id, origin="recurring",
            )  # fmt: skip
        except Exception:
            await session.rollback()
            await session.execute(
                delete(RecurringPosting).where(
                    RecurringPosting.item_id == item.id, RecurringPosting.due_on == d
                )
            )
            await session.commit()
            raise
        posting = await session.get(RecurringPosting, (item.id, d))
        assert posting is not None
        posting.transaction_id = tx.id
        await session.commit()
        n += 1
    return n


async def projection(
    session: AsyncSession, *, viewer_id: UUID, space_id: UUID, today: date,
    months: int = PROJECTION_MONTHS,
) -> dict[str, Any]:  # fmt: skip
    """Próximos `months` meses só com os fixos: o mês corrente conta as datas depois de hoje (as
    de hoje para trás já são lançamentos reais). Saldo projetado = saldo atual das contas do
    espaço + resultado acumulado.
    # ponytail: a data de hoje só entra depois que o job do dia a lança; sem fuso por usuário"""
    await require_member(session, viewer_id, space_id)
    items = list(
        await session.scalars(
            select(RecurringItem).where(
                RecurringItem.space_id == space_id, RecurringItem.active.is_(True)
            )
        )
    )
    first = today.replace(day=1)
    starts = [add_months(first, n) for n in range(months)]
    end = add_months(first, months) - timedelta(days=1)
    names = {
        a.id: a.name
        for a in await session.scalars(select(Account).where(Account.space_id == space_id))
    }
    income = [0] * months
    expense = [0] * months
    loans_m = [0] * months
    upcoming: list[dict[str, Any]] = []
    for i in items:
        for d in occurrences(i, today + timedelta(days=1), end):
            k = (d.year - first.year) * 12 + d.month - first.month
            if i.type == "income":
                income[k] += i.amount_cents
            else:
                expense[k] += i.amount_cents
            if d <= today + timedelta(days=30):
                upcoming.append({
                    "due_on": d, "description": i.description, "type": i.type,
                    "amount_cents": i.amount_cents, "account_id": i.account_id,
                    "account_name": names.get(i.account_id, ""),
                })  # fmt: skip
    # parcelas em aberto de financiamentos/consórcios são gasto (atrasadas caem no mês corrente)
    for loan in await session.scalars(
        select(Loan).where(Loan.space_id == space_id, Loan.canceled_at.is_(None))
    ):
        for inst in await list_installments(session, loan):
            if inst.state == "open" and inst.due_on <= end:
                idx = (inst.due_on.year - first.year) * 12 + inst.due_on.month - first.month
                loans_m[max(0, idx)] += inst.amount_cents
    balance = sum([await account_balance(session, a) for a in names])
    rows = []
    for k, m in enumerate(starts):
        out = expense[k] + loans_m[k]
        balance += income[k] - out
        rows.append({
            "month": m, "income_cents": income[k], "expense_cents": out,
            "expense_loans_cents": loans_m[k],
            "net_cents": income[k] - out, "projected_balance_cents": balance,
        })  # fmt: skip
    upcoming.sort(key=lambda u: (u["due_on"], u["description"]))
    return {"months": rows, "upcoming": upcoming[:10]}
