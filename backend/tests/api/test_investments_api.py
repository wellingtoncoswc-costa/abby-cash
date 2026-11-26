from datetime import date

from app.domain.investments import service as svc
from app.domain.investments.quotes import Quote
from tests.factories import auth, make_account, make_user


async def test_investment_flow_over_http(client, session, monkeypatch):
    async def fake(ticker, days, transport=None):
        return [Quote(date(2026, 1, 15), 3850)]

    monkeypatch.setattr(svc, "fetch_quotes", fake)
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    acc = await make_account(session, a.default_space_id, initial=100_000)
    r = await client.post(
        f"/spaces/{sp}/investments", headers=h,
        json={"kind": "stock", "name": "Petrobras", "ticker": "petr4"},
    )  # fmt: skip
    assert r.status_code == 201 and r.json()["ticker"] == "PETR4"
    inv = r.json()
    b = await client.post(
        f"/investments/{inv['id']}/buys", headers=h,
        json={"account_id": str(acc.id), "quantity": "10", "occurred_on": "2026-01-15"},
    )  # fmt: skip
    assert b.status_code == 201 and b.json()["amount_cents"] == 38_500
    assert (await client.get(f"/accounts/{acc.id}", headers=h)).json()["balance_cents"] == 61_500
    d = (await client.get(f"/spaces/{sp}/investments/dashboard", headers=h)).json()
    assert d["contributed_cents"] == 38_500 and d["assets"][0]["ticker"] == "PETR4"
    over = await client.post(
        f"/investments/{inv['id']}/redeems", headers=h,
        json={"account_id": str(acc.id), "quantity": "11", "occurred_on": "2026-01-15"},
    )  # fmt: skip
    assert over.status_code == 422 and over.json() == {"detail": "insufficient_position"}
    nope = await client.delete(f"/investments/{inv['id']}", headers=h)
    assert nope.status_code == 422 and nope.json() == {"detail": "investment_has_history"}


async def test_validation_and_access(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    sp = str(a.default_space_id)
    bad = await client.post(
        f"/spaces/{sp}/investments", headers=auth(a), json={"kind": "cdb", "name": "x"}
    )
    assert bad.status_code == 422 and bad.json() == {"detail": "invalid_investment"}
    r = await client.get(f"/spaces/{sp}/investments/dashboard", headers=auth(b))
    assert r.status_code in (403, 404)


async def test_asset_panel_over_http(client, session, monkeypatch):
    async def fake(ticker, days, transport=None):
        return [Quote(date(2026, 1, 15), 3850)]

    monkeypatch.setattr(svc, "fetch_quotes", fake)
    a = await make_user(session, "pa@x.com")
    h, sp = auth(a), str(a.default_space_id)
    acc = await make_account(session, a.default_space_id, initial=100_000)
    inv = (
        await client.post(
            f"/spaces/{sp}/investments",
            headers=h,
            json={"kind": "stock", "name": "P", "ticker": "PETR4"},
        )
    ).json()
    await client.post(
        f"/investments/{inv['id']}/buys",
        headers=h,
        json={"account_id": str(acc.id), "quantity": "2", "occurred_on": "2026-01-15"},
    )
    p = await client.get(f"/investments/{inv['id']}/panel", headers=h)
    assert p.status_code == 200 and p.json()["movements"][0]["amount_cents"] == 7_700
    other = await make_user(session, "pb@x.com")
    assert (
        await client.get(f"/investments/{inv['id']}/panel", headers=auth(other))
    ).status_code in (403, 404)
