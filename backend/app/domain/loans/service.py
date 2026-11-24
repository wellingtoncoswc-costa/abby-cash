from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import add_months
from app.domain.accounts.access import use_account
from app.domain.audit import audit, snap
from app.domain.bills.models import Bill, BillReminderSent
from app.domain.errors import DomainError
from app.domain.loans.models import Loan
from app.domain.spaces.access import require_member
from app.domain.transactions.models import Transaction
from app.domain.transactions.rules import check_common

AHEAD = 3  # parcelas em aberto mantidas geradas


@dataclass(frozen=True)
class LoanProgress:
    paid_count: int
    remaining_count: int
    remaining_cents: int
    next_due_on: date | None
    last_due_on: date
    progress_pct: int


def due_on(loan: Loan, number: int) -> date:
    """Dia nominal do 1º vencimento a cada mês (31/jan -> 28/fev -> 31/mar)."""
    return add_months(loan.first_due_on, number - 1)


async def visible_loan(
    session: AsyncSession, viewer_id: UUID, loan_id: UUID, *, lock: bool = False
) -> Loan:
    loan = await session.get(Loan, loan_id, with_for_update=lock)
    if loan is None:
        raise HTTPException(status_code=404, detail="not_found")
    await require_member(session, viewer_id, loan.space_id)
    return loan


def _bill(loan: Loan, n: int, *, historical: bool = False) -> Bill:
    return Bill(
        space_id=loan.space_id, kind="manual", amount_cents=loan.installment_cents,
        description=f"{loan.name} ({n}/{loan.installments_total})", due_on=due_on(loan, n),
        category_id=loan.category_id, loan_id=loan.id, installment_number=n,
        status="paid" if historical else "open",
        settled_historical_at=datetime.now(UTC) if historical else None,
    )  # fmt: skip


async def ensure_installments(session: AsyncSession, loan: Loan) -> None:
    """Mantém geradas as AHEAD primeiras parcelas não pagas (baixa histórica conta como paga),
    sem passar do total. Não faz commit; quem chama já deve segurar o lock do empréstimo."""
    if loan.canceled_at is not None:
        return
    have = dict(
        (
            await session.execute(
                select(Bill.installment_number, Bill.status).where(Bill.loan_id == loan.id)
            )
        ).all()
    )
    slots = 0  # ponytail: percorre até 480 números por chamada; barato frente a uma ida ao banco
    for n in range(1, loan.installments_total + 1):
        if slots >= AHEAD:
            break
        if have.get(n) == "paid":
            continue
        slots += 1
        if n not in have:
            session.add(_bill(loan, n))
    await session.flush()


async def create_loan(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, kind: str, name: str,
    installment_cents: int, installments_total: int, first_due_on: date,
    category_id: UUID | None = None, account_id: UUID | None = None, notes: str | None = None,
    paid_installments: int = 0,
) -> Loan:  # fmt: skip
    if kind not in ("financing", "consortium") or not 1 <= installments_total <= 480:
        raise DomainError("invalid_loan")
    if not 0 <= paid_installments <= installments_total:
        raise DomainError("invalid_paid_installments")
    await check_common(
        session, actor_id=actor_id, space_id=space_id, type="expense",
        amount_cents=installment_cents, category_id=category_id, occurred_on=first_due_on,
    )  # fmt: skip
    if account_id is not None:
        await use_account(session, actor_id, account_id)
    loan = Loan(
        space_id=space_id, kind=kind, name=name, installment_cents=installment_cents,
        installments_total=installments_total, first_due_on=first_due_on,
        category_id=category_id, account_id=account_id, notes=notes,
    )  # fmt: skip
    if not date(2000, 1, 1) <= due_on(loan, installments_total) <= date(2100, 12, 31):
        raise DomainError("invalid_date")
    session.add(loan)
    await session.flush()
    session.add_all(_bill(loan, n, historical=True) for n in range(1, paid_installments + 1))
    await ensure_installments(session, loan)
    audit(session, actor_id, "loan.create", "loan", loan.id,
          {"space_id": str(space_id), "installment_cents": installment_cents,
           "installments_total": installments_total,
           "paid_installments": paid_installments})  # fmt: skip
    await session.commit()
    return loan


async def loan_progress(session: AsyncSession, loan: Loan) -> LoanProgress:
    last = due_on(loan, loan.installments_total)
    paid, generated = (
        await session.execute(
            select(func.count().filter(Bill.status == "paid"), func.count()).where(
                Bill.loan_id == loan.id
            )
        )
    ).one()
    if loan.canceled_at is not None:
        return LoanProgress(paid, 0, 0, None, last, paid * 100 // loan.installments_total)
    unpaid = select(Bill.id).where(Bill.loan_id == loan.id, Bill.status != "paid")
    owed = int(
        await session.scalar(
            select(func.coalesce(func.sum(Bill.amount_cents), 0)).where(Bill.id.in_(unpaid))
        )
        or 0
    ) - int(
        await session.scalar(
            select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
                Transaction.bill_id.in_(unpaid)
            )
        )
        or 0
    )
    not_generated = loan.installments_total - generated
    nxt = await session.scalar(select(func.min(Bill.due_on)).where(Bill.id.in_(unpaid)))
    return LoanProgress(
        paid, loan.installments_total - paid, owed + not_generated * loan.installment_cents,
        nxt, last, paid * 100 // loan.installments_total,
    )  # fmt: skip


async def list_loans(session: AsyncSession, *, viewer_id: UUID, space_id: UUID) -> list[Loan]:
    await require_member(session, viewer_id, space_id)
    return list(
        await session.scalars(
            select(Loan)
            .where(Loan.space_id == space_id, Loan.canceled_at.is_(None))
            .order_by(Loan.created_at)
        )
    )


async def update_loan(
    session: AsyncSession, *, actor_id: UUID, loan_id: UUID, fields: dict[str, Any]
) -> Loan:
    """name / installment_cents: valem para as parcelas ainda sem pagamento."""
    loan = await visible_loan(session, actor_id, loan_id, lock=True)
    if loan.canceled_at is not None:
        raise DomainError("loan_canceled")
    if "installment_cents" in fields:
        await check_common(
            session, actor_id=actor_id, space_id=loan.space_id, type="expense",
            category_id=None, amount_cents=fields["installment_cents"],
            occurred_on=loan.first_due_on,
        )  # fmt: skip
    before = snap(loan, fields)
    for k, v in fields.items():
        setattr(loan, k, v)
    for b in await session.scalars(
        select(Bill).where(Bill.loan_id == loan.id, Bill.status == "open").with_for_update()
    ):
        b.amount_cents = loan.installment_cents
        b.description = f"{loan.name} ({b.installment_number}/{loan.installments_total})"
    audit(session, actor_id, "loan.update", "loan", loan.id,
          {"space_id": str(loan.space_id), "before": before,
           "after": snap(loan, fields)})  # fmt: skip
    await session.commit()
    return loan


async def cancel_loan(session: AsyncSession, *, actor_id: UUID, loan_id: UUID) -> None:
    """Apaga as parcelas sem pagamento; as pagas (e parciais) ficam como histórico."""
    loan = await visible_loan(session, actor_id, loan_id, lock=True)
    if loan.canceled_at is None:
        open_bills = select(Bill.id).where(Bill.loan_id == loan.id, Bill.status == "open")
        await session.execute(
            delete(BillReminderSent).where(BillReminderSent.bill_id.in_(open_bills))
        )
        await session.execute(delete(Bill).where(Bill.id.in_(open_bills)))
        loan.canceled_at = datetime.now(UTC)
        audit(session, actor_id, "loan.cancel", "loan", loan.id, {"space_id": str(loan.space_id)})
        await session.commit()


async def top_up_after_payment(session: AsyncSession, bill: Bill) -> None:
    """Chamado ao pagar uma parcela: gera a seguinte. Não faz commit."""
    if bill.loan_id is not None:
        loan = await session.get(Loan, bill.loan_id, with_for_update=True)
        if loan is not None:
            await ensure_installments(session, loan)


@dataclass(frozen=True)
class Installment:
    number: int
    due_on: date
    amount_cents: int
    state: str  # open | paid_history | paid_real
    bill_id: UUID | None


def _installment(loan: Loan, n: int, bill: Bill | None) -> Installment:
    if bill is None:
        return Installment(n, due_on(loan, n), loan.installment_cents, "open", None)
    state = (
        "paid_history"
        if bill.settled_historical_at
        else "paid_real"
        if bill.status == "paid"
        else "open"
    )  # parcela parcial segue "open"
    return Installment(n, bill.due_on, bill.amount_cents, state, bill.id)


async def list_installments(session: AsyncSession, loan: Loan) -> list[Installment]:
    """Todas as parcelas 1..N, inclusive as ainda não geradas (calculadas)."""
    bills = {
        int(b.installment_number or 0): b
        for b in await session.scalars(select(Bill).where(Bill.loan_id == loan.id))
    }
    nums = sorted(bills) if loan.canceled_at else range(1, loan.installments_total + 1)
    return [_installment(loan, n, bills.get(n)) for n in nums]


async def _locked_installment(
    session: AsyncSession, actor_id: UUID, loan_id: UUID, number: int
) -> tuple[Loan, Bill | None]:
    loan = await visible_loan(session, actor_id, loan_id, lock=True)
    if loan.canceled_at is not None:
        raise DomainError("loan_canceled")
    if not 1 <= number <= loan.installments_total:
        raise DomainError("invalid_installment")
    bill = await session.scalar(
        select(Bill)
        .where(Bill.loan_id == loan.id, Bill.installment_number == number)
        .with_for_update()
    )
    return loan, bill


async def materialize_installment(
    session: AsyncSession, *, actor_id: UUID, loan_id: UUID, number: int
) -> Bill:
    """Gera a parcela (aberta) se ainda não existe, para poder pagá-la de verdade."""
    loan, bill = await _locked_installment(session, actor_id, loan_id, number)
    if bill is None:
        bill = _bill(loan, number)
        session.add(bill)
        await session.flush()
        await ensure_installments(session, loan)
        await session.commit()
    return bill


async def settle_installment(
    session: AsyncSession, *, actor_id: UUID, loan_id: UUID, number: int
) -> Installment:
    """Baixa histórica: já estava paga antes do cadastro; sem lançamento. Idempotente."""
    loan, bill = await _locked_installment(session, actor_id, loan_id, number)
    if bill is None:
        bill = _bill(loan, number, historical=True)
        session.add(bill)
    elif bill.settled_historical_at is not None:
        return _installment(loan, number, bill)
    elif bill.status != "open":
        raise HTTPException(409, "installment_paid_real" if bill.status == "paid"
                            else "installment_partial")  # fmt: skip
    else:
        bill.status, bill.settled_historical_at = "paid", datetime.now(UTC)
    await session.flush()
    await ensure_installments(session, loan)
    audit(session, actor_id, "loan.installment_settle", "bill", bill.id,
          {"space_id": str(loan.space_id), "loan_id": str(loan.id), "number": number})  # fmt: skip
    await session.commit()
    return _installment(loan, number, bill)


async def unsettle_installment(
    session: AsyncSession, *, actor_id: UUID, loan_id: UUID, number: int
) -> Installment:
    """Desfaz a baixa histórica (volta a aberta). Pagamento real: 409. Idempotente."""
    loan, bill = await _locked_installment(session, actor_id, loan_id, number)
    if bill is not None and bill.settled_historical_at is not None:
        bill.status, bill.settled_historical_at = "open", None
        data = {"space_id": str(loan.space_id), "loan_id": str(loan.id), "number": number}
        audit(session, actor_id, "loan.installment_unsettle", "bill", bill.id, data)
        await session.commit()
    elif bill is not None and bill.status == "paid":
        raise HTTPException(409, "installment_paid_real")
    return _installment(loan, number, bill)
