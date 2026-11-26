from tests.factories import auth, make_account, make_user


async def test_panel_over_http(client, session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=10_000)
    r = await client.get(f"/accounts/{acc.id}/panel?month=2026-11", headers=auth(a))
    assert r.status_code == 200 and r.json()["month"] == "2026-11-01"
    assert r.json()["income_cents"] == 0 and r.json()["pockets"] == []
    bad = await client.get(f"/accounts/{acc.id}/panel?month=2026-13", headers=auth(a))
    assert bad.status_code == 422
    other = await make_user(session, "b@x.com")
    r2 = await client.get(f"/accounts/{acc.id}/panel", headers=auth(other))
    assert r2.status_code in (403, 404)
