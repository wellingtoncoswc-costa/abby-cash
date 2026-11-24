from datetime import date, timedelta

from sqlalchemy import select

from app.core.dates import local_today
from app.domain.bills.service import create_bill
from app.domain.cards.service import register_card_purchase
from app.domain.goals.service import contribute, create_goal
from app.domain.payments import pay_invoice
from app.domain.transactions.models import Transaction
from app.domain.transactions.service import account_balance, create_transaction
from tests.factories import auth, category_id, make_account, make_card, make_user

RANGE = "start=2026-11-01&end=2026-11-30"


async def _tx(session, u, acc, amount, on, *, type="expense", cat=None, merchant=None, space=None):
    return await create_transaction(
        session, actor_id=u.id, space_id=space or u.default_space_id, type=type,
        amount_cents=amount, occurred_on=on, account_id=acc.id, category_id=cat,
        merchant=merchant,
    )  # fmt: skip


async def _get(client, u, qs, space=None):
    return await client.get(
        f"/spaces/{space or u.default_space_id}/reports/overview?{qs}", headers=auth(u)
    )


async def test_parity_with_budget_card_by_due_and_transfers_excluded(client, session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp, initial=500_000)
    acc2 = await make_account(session, sp, name="Outra")
    card = await make_card(session, a, sp)  # fecha 10, vence 20
    await register_card_purchase(
        session, actor_id=a.id, space_id=sp, card_id=card.id, amount_cents=30_000,
        occurred_on=date(2026, 10, 15), installments=1,
    )  # fmt: skip  # fatura vence 20/11
    (buy,) = await register_card_purchase(
        session, actor_id=a.id, space_id=sp, card_id=card.id, amount_cents=7_000,
        occurred_on=date(2026, 11, 15), installments=1,
    )  # fmt: skip  # vence 20/12
    await _tx(session, a, acc, 2_000, date(2026, 11, 3))
    await _tx(session, a, acc, 9_000, date(2026, 11, 4), type="income")
    await create_transaction(
        session, actor_id=a.id, space_id=sp, type="transfer", amount_cents=4_000,
        occurred_on=date(2026, 11, 6), account_id=acc.id, counter_account_id=acc2.id,
    )  # fmt: skip
    goal = await create_goal(
        session, actor_id=a.id, space_id=sp, name="Viagem", target_cents=100_000,
        created_on=date(2026, 11, 1)
    )  # fmt: skip
    await contribute(
        session, actor_id=a.id, goal_id=goal.id, from_account_id=acc.id, amount_cents=5_000,
        on=date(2026, 11, 7),
    )  # fmt: skip
    await pay_invoice(
        session, actor_id=a.id, invoice_id=buy.invoice_id, account_id=acc.id,
        paid_on=date(2026, 11, 18), amount_cents=7_000,
    )  # fmt: skip
    await client.put(f"/spaces/{sp}/budgets/2026-11", json={"limit_cents": 100_000},
                     headers=auth(a))  # fmt: skip
    spent = (await client.get(f"/spaces/{sp}/budgets/2026-11", headers=auth(a))).json()[
        "spent_cents"
    ]
    r = await _get(client, a, RANGE)
    assert r.status_code == 200
    t = r.json()["totals"]
    assert spent == 32_000 and t["expense_cents"] == spent  # 30.000 do cartão (venc. nov) + 2.000
    assert t["income_cents"] == 9_000 and t["net_cents"] == 9_000 - 32_000 and t["tx_count"] == 3
    assert t["avg_daily_expense_cents"] == 32_000 // 30
    j = r.json()
    assert {d["date"] for d in j["by_day"]} == {"2026-11-03", "2026-11-04", "2026-11-20"}
    assert any(
        x["name"] == "Cartão de crédito" and x["account_id"] is None for x in j["by_account"]
    )
    # previous: 1..30 de outubro-ish (30 dias antes de 01/11): compra de cartão vence em nov
    assert j["previous"]["expense_cents"] == 0


async def test_previous_period_filters_none_and_groupings(client, session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp, name="Nubank")
    acc2 = await make_account(session, sp, name="Itaú")
    mercado = await category_id(session, sp)
    await _tx(session, a, acc, 10_000, date(2026, 11, 2), cat=mercado, merchant="Pão")  # seg
    await _tx(session, a, acc, 30_000, date(2026, 11, 9), cat=mercado, merchant="Pão")  # seg
    await _tx(session, a, acc2, 20_000, date(2026, 11, 10))  # sem categoria/estabelecimento
    await _tx(session, a, acc2, 5_000, date(2026, 10, 25))  # período anterior (2 a 31/10 -> não)
    await _tx(session, a, acc, 4_000, date(2026, 10, 15))  # dentro do anterior de nov 1-30
    j = (await _get(client, a, RANGE)).json()
    assert j["totals"]["expense_cents"] == 60_000
    assert j["previous"]["expense_cents"] == 9_000 and j["previous"]["tx_count"] == 2
    cats = j["by_category"]
    assert [(c["name"], c["expense_cents"], c["count"]) for c in cats] == [
        ("Mercado", 40_000, 2), ("Sem categoria", 20_000, 1)]  # fmt: skip
    assert cats[0]["share_bp"] == 6666 and cats[1]["share_bp"] == 3333
    assert [(m["merchant"], m["expense_cents"]) for m in j["by_merchant"]] == [
        ("Pão", 40_000), ("Sem estabelecimento", 20_000)]  # fmt: skip
    assert {x["name"] for x in j["by_account"]} == {"Nubank", "Itaú"}
    assert {(d["dow"], d["expense_cents"], d["count"]) for d in j["by_weekday"]} == {
        (0, 40_000, 2), (1, 20_000, 1)}  # fmt: skip
    assert [x["amount_cents"] for x in j["largest"]] == [30_000, 20_000, 10_000]
    # filtros combinados
    none = (await _get(client, a, f"{RANGE}&category_id=none")).json()
    assert none["totals"]["expense_cents"] == 20_000
    both = await _get(client, a, f"{RANGE}&category_id={mercado}&account_id={acc.id}&merchant=Pão")
    assert both.json()["totals"]["expense_cents"] == 40_000
    no_m = (
        await _get(client, a, f"{RANGE}&merchant=Sem estabelecimento&account_id={acc2.id}")
    ).json()
    assert no_m["totals"]["expense_cents"] == 20_000
    assert (await _get(client, a, f"{RANGE}&category_id={mercado}&account_id={acc2.id}")).json()[
        "totals"]["expense_cents"] == 0  # fmt: skip
    inc = (await _get(client, a, f"{RANGE}&type=income")).json()
    assert inc["totals"]["expense_cents"] == 0 and inc["by_category"] == []
    assert (await _get(client, a, f"{RANGE}&category_id=xx")).status_code == 422
    assert (await _get(client, a, f"{RANGE}&type=transfer")).status_code == 422


async def test_twelve_months_with_holes_and_balance_series(client, session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    acc2 = await make_account(session, sp, name="Poup", initial=50_000)
    await _tx(session, a, acc, 1_000, date(2026, 11, 3))
    await _tx(session, a, acc, 7_000, date(2026, 6, 3), type="income")
    await _tx(session, a, acc, 300, date(2025, 12, 31))  # fora da janela, entra no saldo
    await create_transaction(
        session, actor_id=a.id, space_id=sp, type="transfer", amount_cents=2_000,
        occurred_on=date(2026, 8, 1), account_id=acc.id, counter_account_id=acc2.id,
    )  # fmt: skip
    j = (await _get(client, a, "start=2026-11-10&end=2026-11-20&category_id=none")).json()
    months = [m["month"] for m in j["by_month"]]
    assert months == ["2025-12", *[f"2026-{m:02d}" for m in range(1, 12)]]
    by = {m["month"]: m for m in j["by_month"]}
    assert by["2026-06"] == {"month": "2026-06", "income_cents": 7_000, "expense_cents": 0,
                             "net_cents": 7_000}  # fmt: skip
    assert by["2026-11"]["expense_cents"] == 1_000 and by["2026-03"]["net_cents"] == 0
    assert by["2025-12"]["expense_cents"] == 300
    assert j["totals"]["tx_count"] == 0  # a janela do período é 10..20/11
    bs = j["balance_series"]
    assert [b["month"] for b in bs] == months
    assert bs[0]["balance_cents"] == 150_000 - 300
    assert bs[-1]["balance_cents"] == (
        await account_balance(session, acc.id) + await account_balance(session, acc2.id)
    )  # fmt: skip
    assert bs[-1]["balance_cents"] == 150_000 - 300 - 1_000 + 7_000


async def test_range_validation_membership_isolation(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp)
    await _tx(session, a, acc, 1_000, date(2026, 11, 3))
    accb = await make_account(session, b.default_space_id)
    await _tx(session, b, accb, 9_999, date(2026, 11, 3))
    for qs in ("start=2026-11-30&end=2026-11-01", "start=2010-01-01&end=2026-11-01"):
        r = await _get(client, a, qs)
        assert r.status_code == 422 and r.json() == {"detail": "invalid_range"}
    assert (await _get(client, a, "start=2016-01-01&end=2026-01-01")).status_code in (200, 422)
    assert (await _get(client, b, RANGE, space=sp)).status_code == 404
    t = (await _get(client, a, RANGE)).json()["totals"]
    assert t["expense_cents"] == 1_000
    assert (await _get(client, a, "start=2026-11-01")).status_code == 422


async def test_huge_values_and_upcoming(client, session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp)
    for d in (3, 4, 5):
        await _tx(session, a, acc, 10**12, date(2026, 11, d))
    j = (await _get(client, a, RANGE)).json()
    assert j["totals"]["expense_cents"] == 3 * 10**12
    assert j["by_category"][0]["share_bp"] == 10_000
    today = local_today(a.tz)
    await create_bill(session, actor_id=a.id, space_id=sp, description="Luz", amount_cents=9_000,
                      due_on=today + timedelta(days=5))  # fmt: skip
    await create_bill(session, actor_id=a.id, space_id=sp, description="Longe", amount_cents=1,
                      due_on=today + timedelta(days=40))  # fmt: skip
    up = (await _get(client, a, RANGE)).json()["upcoming"]
    assert [(u["kind"], u["description"], u["amount_cents"]) for u in up] == [
        ("bill", "Luz", 9_000)
    ]


async def test_transactions_list_extended_filters(client, session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp)
    card = await make_card(session, a, sp)
    await register_card_purchase(
        session, actor_id=a.id, space_id=sp, card_id=card.id, amount_cents=3_000,
        occurred_on=date(2026, 10, 15), installments=1,
    )  # fmt: skip  # vence 20/11
    await _tx(session, a, acc, 1_000, date(2026, 11, 3), merchant="Pão")
    await _tx(session, a, acc, 500, date(2026, 11, 4), type="income")
    base = f"/spaces/{sp}/transactions?start=2026-11-01&end=2026-11-30"
    h = auth(a)
    assert len((await client.get(base, headers=h)).json()) == 2  # padrão: data do lançamento
    r = await client.get(base + "&effective=true&type=expense&uncategorized=true", headers=h)
    assert sorted(t["amount_cents"] for t in r.json()) == [1_000, 3_000]
    assert r.headers["X-Total-Count"] == "2"
    r = await client.get(base + "&merchant=Pão&limit=1000", headers=h)
    assert [t["amount_cents"] for t in r.json()] == [1_000]
    assert (await client.get(base + "&limit=1001", headers=h)).status_code == 422
    n = await session.scalar(select(Transaction.id).limit(1))
    assert n is not None
