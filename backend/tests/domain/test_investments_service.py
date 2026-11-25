from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.domain.errors import DomainError
from app.domain.investments import service as svc
from app.domain.investments.quotes import Quote
from app.domain.transactions.service import account_balance
from tests.factories import make_account, make_user

D = date(2026, 1, 15)


@pytest.fixture
def quotes(monkeypatch):
    async def fake(ticker, days, transport=None):
        if ticker == "NOPE3":
            raise DomainError("unknown_ticker")
        return [Quote(date(2026, 1, 14), 3800), Quote(D, 3850)]

    monkeypatch.setattr(svc, "fetch_quotes", fake)


async def _stock(session, user):
    return await svc.create_investment(
        session, actor_id=user.id, space_id=user.default_space_id, kind="stock", name="Petrobras",
        ticker="petr4", today=D,
    )  # fmt: skip


async def test_create_validates_kind_fields_and_ticker(session, quotes):
    a = await make_user(session, "a@x.com")
    inv = await _stock(session, a)
    assert inv.ticker == "PETR4"
    sp = a.default_space_id
    with pytest.raises(DomainError, match="unknown_ticker"):
        await svc.create_investment(
            session, actor_id=a.id, space_id=sp, kind="stock", name="x", ticker="NOPE3", today=D
        )
    with pytest.raises(DomainError, match="invalid_investment"):  # CDB sem taxa
        await svc.create_investment(
            session, actor_id=a.id, space_id=sp, kind="cdb", name="CDB", today=D
        )
    with pytest.raises(DomainError, match="invalid_investment"):  # FII sem ticker
        await svc.create_investment(
            session, actor_id=a.id, space_id=sp, kind="fii", name="x", today=D
        )


async def test_buy_stock_uses_dated_price_and_moves_money(session, quotes):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    inv = await _stock(session, a)
    m = await svc.buy(
        session, actor_id=a.id, investment_id=inv.id, account_id=acc.id, on=D,
        quantity=Decimal("10"), today=D,
    )  # fmt: skip
    assert (m.unit_price_cents, m.amount_cents) == (3850, 38_500)  # preço do dia, guardado
    assert await account_balance(session, acc.id) == 61_500
    edited = await svc.buy(
        session, actor_id=a.id, investment_id=inv.id, account_id=acc.id, on=D,
        quantity=Decimal("1"), unit_price_cents=4000, today=D,
    )  # fmt: skip
    assert edited.amount_cents == 4000  # preço editável (preço médio da corretora)


async def test_redeem_limits_and_returns_money(session, quotes):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    inv = await _stock(session, a)
    await svc.buy(
        session, actor_id=a.id, investment_id=inv.id, account_id=acc.id, on=D,
        quantity=Decimal("10"), today=D,
    )  # fmt: skip
    with pytest.raises(DomainError, match="insufficient_position"):
        await svc.redeem(
            session, actor_id=a.id, investment_id=inv.id, account_id=acc.id, on=D,
            quantity=Decimal("10.5"), today=D,
        )  # fmt: skip
    await svc.redeem(
        session, actor_id=a.id, investment_id=inv.id, account_id=acc.id, on=D,
        quantity=Decimal("4"), today=D,
    )  # fmt: skip
    assert await account_balance(session, acc.id) == 61_500 + 15_400


async def test_fixed_income_buy_redeem_and_access(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    cdb = await svc.create_investment(
        session, actor_id=a.id, space_id=a.default_space_id, kind="cdb", name="CDB 110%",
        rate_type="cdi_pct", rate_bp=11000, today=D,
    )  # fmt: skip
    await svc.buy(
        session, actor_id=a.id, investment_id=cdb.id, account_id=acc.id, on=D,
        amount_cents=50_000, today=D,
    )  # fmt: skip
    with pytest.raises(DomainError, match="insufficient_position"):
        await svc.redeem(
            session, actor_id=a.id, investment_id=cdb.id, account_id=acc.id, on=D,
            amount_cents=50_001, today=D,
        )  # fmt: skip
    with pytest.raises(HTTPException) as e:  # outro usuário não acessa
        await svc.buy(
            session, actor_id=b.id, investment_id=cdb.id, account_id=acc.id, on=D,
            amount_cents=1, today=D,
        )  # fmt: skip
    assert e.value.status_code in (403, 404)
