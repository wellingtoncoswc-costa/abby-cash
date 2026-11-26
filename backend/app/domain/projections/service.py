from calendar import monthrange
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import add_months
from app.domain.accounts.models import Account
from app.domain.bills.models import Bill
from app.domain.bills.status import bill_paid_cents
from app.domain.budgets.service import EFFECTIVE_ON
from app.domain.cards.service import invoice_remaining
from app.domain.errors import DomainError
from app.domain.loans.models import Loan
from app.domain.loans.service import due_on, list_installments
from app.domain.recurring.models import RecurringItem
from app.domain.recurring.service import occurrences
from app.domain.reports.service import EXPENSE, INCOME, _q, balance_series
from app.domain.spaces.access import require_member
from app.domain.transactions.models import Transaction as T
from app.domain.transactions.service import Filters, account_balance

VARIABLE_MONTHS = 3  # janela da média dos gastos/receitas variáveis


async def _variable_average(session: AsyncSession, space_id: UUID, first: date) -> tuple[int, int]:
    """Média mensal (receita, despesa) dos 3 meses completos anteriores, só à vista e sem o que
    já é compromisso conhecido (cartão, conta a pagar/parcela, fixos lançados pelo job)."""
    start, end = add_months(first, -VARIABLE_MONTHS), first - timedelta(days=1)

    async def total(kind: str, *extra: Any) -> int:
        q = select(func.coalesce(func.sum(T.amount_cents), 0)).where(
            T.space_id == space_id, T.type == kind, T.card_id.is_(None), T.origin != "recurring",
            T.occurred_on >= start, T.occurred_on <= end, *extra,
        )  # fmt: skip
        return int((await session.scalar(q)) or 0) // VARIABLE_MONTHS

    return await total("income"), await total("expense", T.bill_id.is_(None))


async def projections(
    session: AsyncSession, *, viewer_id: UUID, space_id: UUID, today: date, months: int = 12
) -> dict[str, Any]:  # fmt: skip
    """Meses projetados (corrente + seguintes) somando fixos, parcelas, faturas, contas a pagar e
    a estimativa de variáveis; mais 12 meses de histórico. O mês corrente só conta o que vence
    depois de hoje; o que já venceu e segue em aberto cai nele.
    # ponytail: parcial paga de parcela/conta conta pelo restante só em contas e faturas;
    # contas recorrentes só existem até o horizonte já gerado (3 meses)."""
    if months not in (6, 12):
        raise DomainError("invalid_months")
    await require_member(session, viewer_id, space_id)
    first = today.replace(day=1)
    end = add_months(first, months) - timedelta(days=1)

    def k(d: date) -> int:
        return max(0, (d.year - first.year) * 12 + d.month - first.month)

    inc_fix, exp_fix, exp_loans, exp_cards, exp_bills = ([0] * months for _ in range(5))
    fixo_keys: set[tuple[int, str, int]] = set()
    items = await session.scalars(
        select(RecurringItem).where(
            RecurringItem.space_id == space_id, RecurringItem.active.is_(True)
        )
    )
    for item in items:
        for d in occurrences(item, today + timedelta(days=1), end):
            (inc_fix if item.type == "income" else exp_fix)[k(d)] += item.amount_cents
            fixo_keys.add((k(d), item.description.strip().lower(), item.amount_cents))

    loans = list(
        await session.scalars(
            select(Loan).where(Loan.space_id == space_id, Loan.canceled_at.is_(None))
        )
    )
    ending = []
    for loan in loans:
        left = 0
        for inst in await list_installments(session, loan):
            if inst.state == "open":
                left += 1
                if inst.due_on <= end:
                    exp_loans[k(inst.due_on)] += inst.amount_cents
        if left:
            ending.append({
                "loan_id": loan.id, "name": loan.name, "kind": loan.kind,
                "last_due_on": due_on(loan, loan.installments_total),
                "installment_cents": loan.installment_cents, "remaining_count": left,
            })  # fmt: skip
    ending.sort(key=lambda e: (e["last_due_on"], e["name"]))

    bills = await session.scalars(
        select(Bill).where(
            Bill.space_id == space_id, Bill.status.in_(("open", "partial")),
            Bill.settled_historical_at.is_(None), Bill.loan_id.is_(None), Bill.due_on <= end,
        )
    )  # fmt: skip
    for b in bills:
        if b.kind == "invoice":
            assert b.invoice_id is not None
            rest = await invoice_remaining(session, b.invoice_id)
            if rest > 0:
                exp_cards[k(b.due_on)] += rest
            continue
        rest = b.amount_cents - await bill_paid_cents(session, b.id)
        key = (k(b.due_on), b.description.strip().lower(), rest)
        if rest > 0 and key not in fixo_keys:  # conta já coberta por um fixo conta uma vez
            exp_bills[k(b.due_on)] += rest

    var_inc, var_exp = await _variable_average(session, space_id, first)
    dim = monthrange(today.year, today.month)[1]
    names = list(await session.scalars(select(Account.id).where(Account.space_id == space_id)))
    current = sum([await account_balance(session, a) for a in names])
    run_c = run = current
    rows = []
    for i in range(months):
        frac = (dim - today.day) / dim if i == 0 else 1
        est_i, est_e = int(var_inc * frac), int(var_exp * frac)
        known = exp_fix[i] + exp_loans[i] + exp_cards[i] + exp_bills[i]
        net_c = inc_fix[i] - known
        run_c += net_c
        run += net_c + est_i - est_e
        rows.append({
            "month": add_months(first, i), "income_fixed_cents": inc_fix[i],
            "income_estimated_cents": est_i, "expense_fixed_cents": exp_fix[i],
            "expense_loans_cents": exp_loans[i], "expense_cards_cents": exp_cards[i],
            "expense_bills_cents": exp_bills[i], "expense_estimated_cents": est_e,
            "net_committed_cents": net_c, "net_cents": net_c + est_i - est_e,
            "projected_balance_committed_cents": run_c, "projected_balance_cents": run,
            "commitment_bp": known * 10_000 // inc_fix[i] if inc_fix[i] > 0 else None,
        })  # fmt: skip

    hfirst = add_months(first, -11)
    hmonths = [add_months(hfirst, n) for n in range(12)]
    month = func.date_trunc("month", EFFECTIVE_ON)
    got = {
        m.date(): (int(i), int(e))
        for m, i, e in await session.execute(
            _q(space_id, Filters(), hfirst, add_months(first, 1) - timedelta(days=1),
               month, INCOME, EXPENSE).group_by(month)
        )
    }  # fmt: skip
    bal = {b["month"]: b["balance_cents"] for b in await balance_series(session, space_id, hmonths)}
    history = [
        {"month": m.strftime("%Y-%m"), "income_cents": got.get(m, (0, 0))[0],
         "expense_cents": got.get(m, (0, 0))[1],
         "net_cents": got.get(m, (0, 0))[0] - got.get(m, (0, 0))[1],
         "balance_cents": bal[m.strftime("%Y-%m")]}
        for m in hmonths
    ]  # fmt: skip
    return {
        "current_balance_cents": current,
        "months": rows,
        "history": history,
        "loans_ending": ending,
        "averages": {
            "estimated_income_cents": var_inc,
            "estimated_expense_cents": var_exp,
            "history_income_cents": sum(h["income_cents"] for h in history) // 12,
            "history_expense_cents": sum(h["expense_cents"] for h in history) // 12,
        },
    }
