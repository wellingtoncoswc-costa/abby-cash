import bisect
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.access import use_account
from app.domain.audit import audit
from app.domain.errors import DomainError
from app.domain.investments.models import Investment, InvestmentMovement, PriceQuote
from app.domain.investments.quotes import fetch_quotes, latest_close, upsert_quotes
from app.domain.investments.valuation import cdi_factors, fixed_value, weekday_factors
from app.domain.pockets.models import CdiRate
from app.domain.spaces.access import require_member
from app.domain.transactions.models import Transaction
from app.domain.transactions.rules import check_common

VARIABLE, FIXED = ("stock", "fii"), ("cdb", "lci", "lca")


async def visible_investment(
    session: AsyncSession, viewer_id: UUID, investment_id: UUID, *, lock: bool = False
) -> Investment:
    inv = await session.get(Investment, investment_id, with_for_update=lock)
    if inv is None:
        raise HTTPException(status_code=404, detail="not_found")
    await require_member(session, viewer_id, inv.space_id)
    return inv


async def create_investment(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, kind: str, name: str, today: date,
    ticker: str | None = None, rate_type: str | None = None, rate_bp: int | None = None,
    maturity_on: date | None = None, transport: Any = None,
) -> Investment:  # fmt: skip
    await require_member(session, actor_id, space_id)
    variable = kind in VARIABLE
    ticker = ticker.strip().upper() if ticker else None
    ok = (variable and ticker and rate_type is None and rate_bp is None) or (
        kind in FIXED and not ticker and rate_type in ("cdi_pct", "fixed") and rate_bp
    )
    if not ok:
        raise DomainError("invalid_investment")
    if variable:  # valida o ticker e já guarda o histórico recente
        assert ticker is not None
        await upsert_quotes(session, ticker, await fetch_quotes(ticker, 30, transport))
    inv = Investment(
        space_id=space_id, kind=kind, name=name, ticker=ticker, rate_type=rate_type,
        rate_bp=rate_bp, maturity_on=maturity_on,
    )  # fmt: skip
    session.add(inv)
    await session.flush()
    audit(session, actor_id, "investment.create", "investment", inv.id,
          {"space_id": str(space_id), "kind": kind})  # fmt: skip
    await session.commit()
    return inv


async def movements(session: AsyncSession, investment_id: UUID) -> list[InvestmentMovement]:
    rows = await session.scalars(
        select(InvestmentMovement)
        .where(InvestmentMovement.investment_id == investment_id)
        .order_by(InvestmentMovement.occurred_on, InvestmentMovement.created_at)
    )
    return list(rows)


def position_qty(movs: list[InvestmentMovement], on: date | None = None) -> Decimal:
    return sum(
        (
            (m.quantity or Decimal(0)) * (1 if m.kind == "buy" else -1)
            for m in movs
            if on is None or m.occurred_on <= on
        ),
        Decimal(0),
    )


async def fixed_factors(
    session: AsyncSession, inv: Investment, start: date, end: date
) -> dict[date, Decimal]:
    assert inv.rate_bp is not None
    if inv.rate_type == "fixed":
        return weekday_factors(start, end, inv.rate_bp)
    rows = await session.execute(
        select(CdiRate.on_date, CdiRate.daily_pct).where(
            CdiRate.on_date > start, CdiRate.on_date <= end
        )
    )
    return cdi_factors({d: p for d, p in rows}, inv.rate_bp)


def fixed_pairs(movs: list[InvestmentMovement]) -> list[tuple[date, int]]:
    return [(m.occurred_on, m.amount_cents if m.kind == "buy" else -m.amount_cents) for m in movs]


async def fixed_value_on(
    session: AsyncSession, inv: Investment, movs: list[InvestmentMovement], on: date
) -> int:
    pairs = [p for p in fixed_pairs(movs) if p[0] <= on]
    if not pairs:
        return 0
    start = min(d for d, _ in pairs)
    return fixed_value(pairs, await fixed_factors(session, inv, start, on), on)


async def _price_on(
    session: AsyncSession, inv: Investment, on: date, today: date, transport: Any
) -> int:
    assert inv.ticker is not None
    q = await latest_close(session, inv.ticker, on)
    if q is None:  # data anterior ao histórico guardado: busca sob demanda
        await upsert_quotes(
            session, inv.ticker, await fetch_quotes(inv.ticker, (today - on).days + 5, transport)
        )
        q = await latest_close(session, inv.ticker, on)
    if q is None:
        raise DomainError("no_quote")
    return q.close_cents


async def _move(
    session: AsyncSession, *, actor_id: UUID, investment_id: UUID, account_id: UUID, on: date,
    kind: str, amount_cents: int | None, quantity: Decimal | None,
    unit_price_cents: int | None, today: date, transport: Any,
) -> InvestmentMovement:  # fmt: skip
    inv = await visible_investment(session, actor_id, investment_id, lock=kind == "redeem")
    await use_account(session, actor_id, account_id)
    movs = await movements(session, inv.id)
    price: int | None
    if inv.kind in VARIABLE:
        if quantity is None or quantity <= 0:
            raise DomainError("invalid_quantity")
        if kind == "redeem" and quantity > position_qty(movs):
            raise DomainError("insufficient_position")
        price = unit_price_cents or await _price_on(session, inv, on, today, transport)
        amount = int((quantity * price).quantize(Decimal(1), ROUND_HALF_EVEN))
    else:
        quantity = price = None
        if amount_cents is None:
            raise DomainError("invalid_amount")
        amount = amount_cents
        if kind == "redeem" and amount > await fixed_value_on(session, inv, movs, on):
            raise DomainError("insufficient_position")
    await check_common(
        session, actor_id=actor_id, space_id=inv.space_id, type="transfer", amount_cents=amount,
        category_id=None, occurred_on=on,
    )  # fmt: skip
    buy = kind == "buy"
    tx = Transaction(
        space_id=inv.space_id, type="transfer", amount_cents=amount, occurred_on=on,
        description=f"{'Aporte' if buy else 'Resgate'}: {inv.name}",
        account_id=account_id if buy else None, counter_account_id=None if buy else account_id,
        created_by=actor_id, origin="web",
    )  # fmt: skip
    session.add(tx)
    await session.flush()
    mv = InvestmentMovement(
        investment_id=inv.id, kind=kind, occurred_on=on, quantity=quantity,
        unit_price_cents=price, amount_cents=amount, account_id=account_id, transaction_id=tx.id,
    )  # fmt: skip
    session.add(mv)
    await session.flush()
    audit(session, actor_id, f"investment.{kind}", "investment", inv.id,
          {"amount_cents": amount, "transaction_id": str(tx.id)})  # fmt: skip
    await session.commit()
    return mv


async def buy(
    session: AsyncSession, *, actor_id: UUID, investment_id: UUID, account_id: UUID, on: date,
    today: date, amount_cents: int | None = None, quantity: Decimal | None = None,
    unit_price_cents: int | None = None, transport: Any = None,
) -> InvestmentMovement:  # fmt: skip
    return await _move(
        session, actor_id=actor_id, investment_id=investment_id, account_id=account_id, on=on,
        kind="buy", amount_cents=amount_cents, quantity=quantity,
        unit_price_cents=unit_price_cents, today=today, transport=transport,
    )  # fmt: skip


async def redeem(
    session: AsyncSession, *, actor_id: UUID, investment_id: UUID, account_id: UUID, on: date,
    today: date, amount_cents: int | None = None, quantity: Decimal | None = None,
    unit_price_cents: int | None = None, transport: Any = None,
) -> InvestmentMovement:  # fmt: skip
    return await _move(
        session, actor_id=actor_id, investment_id=investment_id, account_id=account_id, on=on,
        kind="redeem", amount_cents=amount_cents, quantity=quantity,
        unit_price_cents=unit_price_cents, today=today, transport=transport,
    )  # fmt: skip


def _bp(num: int, den: int) -> int | None:
    return num * 10000 // den if den > 0 else None


def _signed(m: InvestmentMovement) -> int:
    return m.amount_cents if m.kind == "buy" else -m.amount_cents


async def dashboard(
    session: AsyncSession, *, viewer_id: UUID, space_id: UUID, today: date, days: int = 365,
    only: UUID | None = None,
) -> dict[str, Any]:  # fmt: skip
    """Posição atual por ativo, totais, alocação por tipo e série diária (valor x aportado).
    # ponytail: série recalculada a cada chamada (O(dias x ativos)); cachear se passar de ~50 ativos
    """
    await require_member(session, viewer_id, space_id)
    q = select(Investment).where(Investment.space_id == space_id)
    invs = list(await session.scalars(q.where(Investment.id == only) if only else q))
    data = {i.id: await movements(session, i.id) for i in invs}
    firsts = [m[0].occurred_on for m in data.values() if m]
    start = max(min(firsts), today - timedelta(days=days)) if firsts else today
    value_on: dict[UUID, Any] = {}
    assets: list[dict[str, Any]] = []
    for i in invs:
        movs = data[i.id]
        contributed = sum(_signed(m) for m in movs)
        a: dict[str, Any] = {
            "id": i.id, "name": i.name, "kind": i.kind, "ticker": i.ticker, "quantity": None,
            "avg_price_cents": None, "price_cents": None, "quote_date": None,
            "day_change_bp": None, "contributed_cents": contributed,
        }  # fmt: skip
        if i.kind in VARIABLE:
            assert i.ticker is not None
            qs = list(
                await session.scalars(
                    select(PriceQuote)
                    .where(PriceQuote.ticker == i.ticker, PriceQuote.on_date <= today)
                    .order_by(PriceQuote.on_date)
                )
            )
            dates = [q.on_date for q in qs]

            def vvar(day: date, qs: Any = qs, dates: Any = dates, movs: Any = movs) -> int:
                k = bisect.bisect_right(dates, day) - 1
                if k < 0:
                    return 0
                v = position_qty(movs, day) * qs[k].close_cents
                return int(v.quantize(Decimal(1), ROUND_HALF_EVEN))

            vv: Any = vvar

            buys = [m for m in movs if m.kind == "buy"]
            bought = sum((m.quantity or Decimal(0) for m in buys), Decimal(0))
            a["quantity"] = format(position_qty(movs).normalize(), "f")
            a["avg_price_cents"] = (
                int(sum(m.amount_cents for m in buys) / bought) if bought else None
            )
            if qs:
                a["price_cents"], a["quote_date"] = qs[-1].close_cents, qs[-1].on_date
                if len(qs) > 1 and qs[-2].close_cents:
                    a["day_change_bp"] = _bp(
                        qs[-1].close_cents - qs[-2].close_cents, qs[-2].close_cents
                    )
        else:
            pairs = fixed_pairs(movs)
            factors = (
                await fixed_factors(session, i, min(d for d, _ in pairs), today) if pairs else {}
            )

            def vfix(day: date, pairs: Any = pairs, factors: Any = factors) -> int:
                return fixed_value([p for p in pairs if p[0] <= day], factors, day)

            vv = vfix

        a["value_cents"] = vv(today)
        value_on[i.id] = vv
        a["profit_cents"] = a["value_cents"] - contributed
        a["profit_bp"] = _bp(a["profit_cents"], contributed)
        assets.append(a)
    live = [i for i in invs if i.id in value_on]
    series = [
        {
            "on": (day := start + timedelta(n)),
            "value_cents": sum(value_on[i.id](day) for i in live),
            "contributed_cents": sum(
                _signed(m) for i in live for m in data[i.id] if m.occurred_on <= day
            ),
        }
        for n in range((today - start).days + 1)
        if firsts
    ]
    by_kind: dict[str, int] = {}
    for a in assets:
        by_kind[a["kind"]] = by_kind.get(a["kind"], 0) + a["value_cents"]
    contributed = sum(a["contributed_cents"] for a in assets)
    current = sum(a["value_cents"] for a in assets)
    return {
        "assets": assets, "by_kind": [{"kind": k, "value_cents": v} for k, v in by_kind.items()],
        "series": series, "contributed_cents": contributed, "current_cents": current,
        "profit_cents": current - contributed, "profit_bp": _bp(current - contributed, contributed),
    }  # fmt: skip


async def investment_panel(
    session: AsyncSession, viewer_id: UUID, investment_id: UUID, *, today: date
) -> dict[str, Any]:
    """Movimentos (mais recentes primeiro) e evolução só deste ativo."""
    inv = await visible_investment(session, viewer_id, investment_id)
    d = await dashboard(
        session, viewer_id=viewer_id, space_id=inv.space_id, today=today, only=inv.id
    )
    return {
        "movements": [
            {
                "id": m.id,
                "kind": m.kind,
                "occurred_on": m.occurred_on,
                "quantity": m.quantity,
                "unit_price_cents": m.unit_price_cents,
                "amount_cents": m.amount_cents,
            }
            for m in reversed(await movements(session, inv.id))
        ],  # fmt: skip
        "series": d["series"],
    }
