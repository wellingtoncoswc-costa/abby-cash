from dataclasses import replace
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Integer, case, cast, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import add_months
from app.domain.accounts.models import Account
from app.domain.bills.models import Bill
from app.domain.budgets.service import EFFECTIVE_ON
from app.domain.categories.models import Category
from app.domain.spaces.access import require_member
from app.domain.transactions.models import Transaction as T
from app.domain.transactions.service import MERCHANT_LABEL, Filters, _filtered

# soma de despesa/receita; sum() de BIGINT vira numeric no Postgres: int() ao ler
EXPENSE = func.coalesce(func.sum(case((T.type == "expense", T.amount_cents), else_=0)), 0)
INCOME = func.coalesce(func.sum(case((T.type == "income", T.amount_cents), else_=0)), 0)
EXPENSE_ONLY = T.type == "expense"


def _q(space_id: UUID, f: Filters, start: date, end: date, *cols: Any) -> Any:
    """Despesas e receitas do espaço pela data efetiva (mesma regra do teto), com os filtros."""
    q = _filtered(space_id, replace(f, start=start, end=end, effective=True, type=f.type))
    # crédito/estorno no cartão (receita com card_id) não é receita: fica fora dos totais
    credit = (T.type == "income") & T.card_id.is_not(None)
    return q.where(T.type.in_(("expense", "income")), ~credit).with_only_columns(
        *cols, maintain_column_froms=True
    )


async def _totals(
    session: AsyncSession, sid: UUID, f: Filters, start: date, end: date
) -> dict[str, int]:
    inc, exp, n = (
        await session.execute(_q(sid, f, start, end, INCOME, EXPENSE, func.count()))
    ).one()
    days = (end - start).days + 1
    return {
        "income_cents": int(inc), "expense_cents": int(exp), "net_cents": int(inc) - int(exp),
        "tx_count": n, "avg_daily_expense_cents": int(exp) // days,
    }  # fmt: skip


def _month_start(d: date) -> date:
    return d.replace(day=1)


async def balance_series(
    session: AsyncSession, sid: UUID, months: list[date]
) -> list[dict[str, Any]]:
    """Saldo total das contas do espaço ao fim de cada mês: inicial + efeito dos lançamentos
    (mesma regra de `signed`/account_balance), agrupado por mês no SQL."""
    mine = select(Account.id).where(Account.space_id == sid)
    m = func.date_trunc("month", T.occurred_on)
    out_ = case((T.type == "income", T.amount_cents), else_=-T.amount_cents)  # + receita, − o resto
    stmt = (
        select(m.label("m"), func.sum(out_))
        .join(Account, Account.id == T.account_id)
        .where(
            T.account_id.in_(mine),
            T.occurred_on < add_months(months[-1], 1),
            or_(Account.opened_on.is_(None), T.occurred_on >= Account.opened_on),
        )
        .group_by(m)
    )
    into = (
        select(m.label("m"), func.sum(T.amount_cents))
        .join(Account, Account.id == T.counter_account_id)
        .where(T.type == "transfer", T.counter_account_id.in_(mine),
               T.occurred_on < add_months(months[-1], 1),
               or_(Account.opened_on.is_(None), T.occurred_on >= Account.opened_on))
        .group_by(m)
    )  # fmt: skip
    delta: dict[date, int] = {}
    for q in (stmt, into):
        for month, v in (await session.execute(q)).all():
            delta[month.date()] = delta.get(month.date(), 0) + int(v)
    initial = int(
        await session.scalar(
            select(func.coalesce(func.sum(Account.initial_balance_cents), 0)).where(
                Account.space_id == sid
            )
        )
        or 0
    )
    before = sum(v for k, v in delta.items() if k < months[0])
    series, run = [], initial + before
    for mo in months:
        run += delta.get(mo, 0)
        series.append({"month": mo.strftime("%Y-%m"), "balance_cents": run})
    return series


async def overview(
    session: AsyncSession, *, viewer_id: UUID, space_id: UUID, start: date, end: date,
    today: date, filters: Filters | None = None,
) -> dict[str, Any]:  # fmt: skip
    await require_member(session, viewer_id, space_id)
    sid, f = space_id, filters or Filters()
    days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    first = add_months(_month_start(end), -11)

    async def rows(*cols: Any, s: date = start, e: date = end, group: Any = None, order: Any = None,
                   where: Any = None, limit: int | None = None) -> list[Any]:  # fmt: skip
        q = _q(sid, f, s, e, *cols)
        if where is not None:
            q = q.where(where)
        if group is not None:
            q = q.group_by(*group)
        if order is not None:
            q = q.order_by(*order)
        return list((await session.execute(q.limit(limit))).all())

    totals = await _totals(session, sid, f, start, end)
    previous = await _totals(session, sid, f, prev_end - timedelta(days=days - 1), prev_end)

    exp = EXPENSE.label("exp")
    cats = await session.execute(
        _q(sid, f, start, end, T.category_id, Category.name, exp, func.count())
        .outerjoin(Category, Category.id == T.category_id)
        .where(EXPENSE_ONLY)
        .group_by(T.category_id, Category.name)
        .order_by(exp.desc(), Category.name)
    )
    total_exp = totals["expense_cents"]
    by_category = [
        {"category_id": cid, "name": name or "Sem categoria", "expense_cents": int(v), "count": n,
         "share_bp": int(v) * 10_000 // total_exp}
        for cid, name, v, n in cats if v > 0
    ]  # fmt: skip
    by_merchant = [
        {"merchant": m, "expense_cents": int(v), "count": n}
        for m, v, n in await rows(
            MERCHANT_LABEL, exp, func.count(), where=EXPENSE_ONLY, group=(MERCHANT_LABEL,),
            order=(exp.desc(), MERCHANT_LABEL), limit=10,
        )
    ]  # fmt: skip
    accs = await session.execute(
        _q(sid, f, start, end, T.account_id, Account.name, T.card_id.is_not(None), INCOME, EXPENSE)
        .outerjoin(Account, Account.id == T.account_id)
        .group_by(T.account_id, Account.name, T.card_id.is_not(None))
        .order_by(Account.name)
    )
    by_account = [
        {"account_id": aid, "name": name or ("Cartão de crédito" if card else "Sem conta"),
         "income_cents": int(i), "expense_cents": int(e)}
        for aid, name, card, i, e in accs
    ]  # fmt: skip
    by_day = [
        {"date": d, "income_cents": int(i), "expense_cents": int(e)}
        for d, i, e in await rows(EFFECTIVE_ON, INCOME, EXPENSE, group=(EFFECTIVE_ON,),
                                  order=(EFFECTIVE_ON,))
    ]  # fmt: skip
    dow = (cast(extract("isodow", EFFECTIVE_ON), Integer) - 1).label("dow")
    by_weekday = [
        {"dow": d, "expense_cents": int(v), "count": n}
        for d, v, n in await rows(dow, exp, func.count(), where=EXPENSE_ONLY, group=(dow,),
                                  order=(dow,))
    ]  # fmt: skip
    largest = [
        {"id": t.id, "occurred_on": t.occurred_on, "description": t.description,
         "merchant": t.merchant, "category_id": t.category_id, "amount_cents": t.amount_cents,
         "type": t.type}
        for t in await session.scalars(
            _q(sid, f, start, end, T).where(EXPENSE_ONLY)
            .order_by(T.amount_cents.desc(), EFFECTIVE_ON.desc(), T.id).limit(5)
        )
    ]  # fmt: skip

    month = func.date_trunc("month", EFFECTIVE_ON)
    got = {
        m.date(): (int(i), int(e))
        for m, i, e in (
            await session.execute(
                _q(sid, f, first, add_months(first, 12) - timedelta(days=1), month, INCOME, EXPENSE)
                .group_by(month)
            )
        )
    }  # fmt: skip
    months = [add_months(first, k) for k in range(12)]
    by_month = [
        {"month": m.strftime("%Y-%m"), "income_cents": got.get(m, (0, 0))[0],
         "expense_cents": got.get(m, (0, 0))[1],
         "net_cents": got.get(m, (0, 0))[0] - got.get(m, (0, 0))[1]}
        for m in months
    ]  # fmt: skip

    paid = (
        select(func.coalesce(func.sum(T.amount_cents), 0))
        .where(T.bill_id == Bill.id)
        .correlate(Bill)
        .scalar_subquery()
    )
    ups = await session.execute(
        select(Bill.kind, Bill.id, Bill.description, Bill.due_on, Bill.amount_cents - paid)
        .where(Bill.space_id == sid, Bill.status.in_(("open", "partial")),
               Bill.due_on >= today, Bill.due_on <= today + timedelta(days=30))
        .order_by(Bill.due_on, Bill.id)
    )  # fmt: skip
    upcoming = [
        {"kind": "invoice" if kind == "invoice" else "bill", "id": i, "description": d,
         "due_on": due, "amount_cents": int(a)}
        for kind, i, d, due, a in ups if a > 0
    ]  # fmt: skip
    return {
        "totals": totals, "previous": previous, "by_category": by_category,
        "by_merchant": by_merchant, "by_account": by_account, "by_day": by_day,
        "by_month": by_month, "by_weekday": by_weekday, "largest": largest,
        "balance_series": await balance_series(session, sid, months), "upcoming": upcoming,
    }  # fmt: skip
