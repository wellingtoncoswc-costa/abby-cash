from datetime import date

from app.domain.transactions.service import create_transaction
from tests.factories import auth, category_id, make_account, make_user


async def test_budget_roundtrip_and_replace(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    mercado = await category_id(session, a.default_space_id)
    acc = await make_account(session, a.default_space_id)
    await create_transaction(
        session, actor_id=a.id, space_id=a.default_space_id, type="expense", amount_cents=20_000,
        occurred_on=date(2026, 11, 8), account_id=acc.id, category_id=mercado,
    )  # fmt: skip
    url = f"/spaces/{sp}/budgets/2026-11"
    body = {
        "limit_cents": 300_000,
        "categories": [{"category_id": str(mercado), "limit_cents": 80_000}],
    }
    put = await client.put(url, json=body, headers=h)
    assert put.status_code == 200
    expected = {
        "month": "2026-11-01", "limit_cents": 300_000, "spent_cents": 20_000,
        "categories": [{"category_id": str(mercado), "limit_cents": 80_000, "spent_cents": 20_000}],
    }  # fmt: skip
    assert put.json() == expected
    assert (await client.get(url, headers=h)).json() == expected
    again = await client.put(url, json={"limit_cents": 250_000}, headers=h)
    assert again.json()["categories"] == [] and again.json()["limit_cents"] == 250_000


async def test_budget_errors(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    ha, hb, sp = auth(a), auth(b), str(a.default_space_id)
    assert (await client.get(f"/spaces/{sp}/budgets/2026-12", headers=ha)).status_code == 404
    for month in ("2026-13", "nov", "2026-11-01", "2026-1", "２０２６-０１"):
        r = await client.get(f"/spaces/{sp}/budgets/{month}", headers=ha)
        assert r.status_code == 422, month
    for bad in (10.5, 0, "100"):
        r = await client.put(f"/spaces/{sp}/budgets/2026-11", json={"limit_cents": bad}, headers=ha)
        assert r.status_code == 422, bad
    assert (await client.put(f"/spaces/{sp}/budgets/2026-11", json={"limit_cents": 100},
                             headers=hb)).status_code == 404  # fmt: skip
    assert (await client.get(f"/spaces/{sp}/budgets/2026-11", headers=hb)).status_code == 404
    other_cat = str(await category_id(session, b.default_space_id))
    r = await client.put(
        f"/spaces/{sp}/budgets/2026-11", headers=ha,
        json={"limit_cents": 100, "categories": [{"category_id": other_cat, "limit_cents": 10}]},
    )  # fmt: skip
    assert r.status_code == 422 and r.json() == {"detail": "invalid_category"}
