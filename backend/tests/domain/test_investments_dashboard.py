from datetime import date
from decimal import Decimal

from app.domain.investments import service as svc
from tests.domain.test_investments_service import quotes  # noqa: F401  (fixture)
from tests.factories import make_account, make_user

D, TODAY = date(2026, 1, 14), date(2026, 1, 16)


async def test_dashboard_profit_series_and_allocation(session, quotes):  # noqa: F811
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=1_000_000)
    inv = await svc.create_investment(
        session, actor_id=a.id, space_id=a.default_space_id, kind="stock", name="Petrobras",
        ticker="PETR4", today=TODAY,
    )  # fmt: skip
    await svc.buy(
        session,
        actor_id=a.id,
        investment_id=inv.id,
        account_id=acc.id,
        on=D,
        quantity=Decimal("10"),
        today=TODAY,
    )  # compra a 38,00 (fechamento do dia 14)
    cdb = await svc.create_investment(
        session, actor_id=a.id, space_id=a.default_space_id, kind="cdb", name="CDB",
        rate_type="fixed", rate_bp=1250, today=TODAY,
    )  # fmt: skip
    await svc.buy(
        session, actor_id=a.id, investment_id=cdb.id, account_id=acc.id, on=D,
        amount_cents=100_000, today=TODAY,
    )  # fmt: skip
    d = await svc.dashboard(session, viewer_id=a.id, space_id=a.default_space_id, today=TODAY)
    stock = next(x for x in d["assets"] if x["ticker"] == "PETR4")
    assert stock["quantity"] == "10" and stock["avg_price_cents"] == 3800
    assert (stock["price_cents"], stock["value_cents"]) == (3850, 38_500)  # último fechamento
    assert stock["profit_cents"] == 500 and stock["day_change_bp"] == 131  # 38,50 vs 38,00
    assert d["contributed_cents"] == 138_000
    assert d["current_cents"] == sum(x["value_cents"] for x in d["assets"])
    assert d["profit_cents"] == d["current_cents"] - 138_000
    assert {k["kind"] for k in d["by_kind"]} == {"stock", "cdb"}
    assert d["series"][0]["on"] == D and d["series"][-1]["on"] == TODAY
    assert d["series"][0]["contributed_cents"] == 138_000


async def test_dashboard_empty(session):
    a = await make_user(session, "a@x.com")
    d = await svc.dashboard(session, viewer_id=a.id, space_id=a.default_space_id, today=TODAY)
    assert d["assets"] == [] and d["series"] == [] and d["profit_bp"] is None


async def test_dashboard_lists_assets_without_movements(session, quotes):  # noqa: F811
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    await svc.create_investment(
        session, actor_id=a.id, space_id=sp, kind="stock", name="Petrobras", ticker="PETR4",
        today=TODAY,
    )  # fmt: skip
    await svc.create_investment(
        session, actor_id=a.id, space_id=sp, kind="cdb", name="CDB", rate_type="fixed",
        rate_bp=1250, today=TODAY,
    )  # fmt: skip
    d = await svc.dashboard(session, viewer_id=a.id, space_id=sp, today=TODAY)
    assert {x["name"] for x in d["assets"]} == {"Petrobras", "CDB"}  # recém-cadastrados aparecem
    assert all(x["value_cents"] == 0 and x["contributed_cents"] == 0 for x in d["assets"])
    stock = next(x for x in d["assets"] if x["ticker"] == "PETR4")
    assert stock["quantity"] == "0" and stock["price_cents"] == 3850
    assert d["series"] == [] and d["profit_bp"] is None


async def test_investment_panel_only_this_asset(session, quotes):  # noqa: F811
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=1_000_000)
    sp = a.default_space_id
    stock = await svc.create_investment(
        session, actor_id=a.id, space_id=sp, kind="stock", name="Petrobras", ticker="PETR4",
        today=TODAY,
    )  # fmt: skip
    cdb = await svc.create_investment(
        session, actor_id=a.id, space_id=sp, kind="cdb", name="CDB", rate_type="fixed",
        rate_bp=1250, today=TODAY,
    )  # fmt: skip
    await svc.buy(session, actor_id=a.id, investment_id=stock.id, account_id=acc.id, on=D,
                  quantity=Decimal("10"), today=TODAY)  # fmt: skip
    await svc.buy(session, actor_id=a.id, investment_id=stock.id, account_id=acc.id, on=TODAY,
                  quantity=Decimal("1"), today=TODAY)  # fmt: skip
    await svc.buy(session, actor_id=a.id, investment_id=cdb.id, account_id=acc.id, on=D,
                  amount_cents=100_000, today=TODAY)  # fmt: skip
    p = await svc.investment_panel(session, a.id, stock.id, today=TODAY)
    assert [m["occurred_on"] for m in p["movements"]] == [TODAY, D]  # mais recente primeiro
    assert p["series"][0]["contributed_cents"] == 38_000  # só a ação, sem o CDB
    assert p["series"][-1]["contributed_cents"] == 38_000 + 3_850
