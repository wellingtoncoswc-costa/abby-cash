from tests.factories import auth, make_account, make_user


async def test_projections_over_http(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    await make_account(session, a.default_space_id, initial=50_000)
    r = await client.get(f"/spaces/{sp}/projections?months=6", headers=h)
    assert r.status_code == 200
    d = r.json()
    assert (
        len(d["months"]) == 6 and len(d["history"]) == 12 and d["current_balance_cents"] == 50_000
    )
    assert d["months"][0]["projected_balance_cents"] == 50_000 and d["loans_ending"] == []
    assert (await client.get(f"/spaces/{sp}/projections?months=7", headers=h)).status_code == 422
    assert (await client.get(f"/spaces/{sp}/projections", headers=h)).status_code == 200
    other = await make_user(session, "b@x.com")
    r2 = await client.get(f"/spaces/{sp}/projections", headers=auth(other))
    assert r2.status_code in (403, 404)
