async def test_pocket_panel_over_http(client, session):
    from tests.factories import auth, make_account, make_user

    a = await make_user(session, "pp@x.com")
    acc = await make_account(session, a.default_space_id)
    r = await client.post(
        f"/spaces/{a.default_space_id}/pockets", headers=auth(a),
        json={"account_id": str(acc.id), "name": "R", "cdi_bp": 10000},
    )  # fmt: skip
    pid = r.json()["id"]
    p = await client.get(f"/pockets/{pid}/panel", headers=auth(a))
    assert p.status_code == 200 and len(p.json()["yield_by_month"]) == 6
    assert p.json()["goals"] == []
    other = await make_user(session, "pq@x.com")
    assert (await client.get(f"/pockets/{pid}/panel", headers=auth(other))).status_code in (
        403,
        404,
    )
