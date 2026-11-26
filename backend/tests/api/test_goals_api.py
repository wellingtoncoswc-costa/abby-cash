from app.core.dates import local_today
from tests.factories import auth, make_account, make_user


async def test_goal_flow_over_http(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    acc = await make_account(session, a.default_space_id, initial=100_000)
    r = await client.post(
        f"/spaces/{sp}/goals", headers=h,
        json={"name": "Viagem", "target_cents": 120_000, "deadline": "2099-07-15",
              "account_ids": [str(acc.id)]},
    )  # fmt: skip
    assert r.status_code == 201
    goal = r.json()
    assert goal["account_ids"] == [str(acc.id)] and goal["pocket_ids"] == []
    assert goal["target_cents"] == 120_000 and goal["created_on"] == local_today(a.tz).isoformat()
    c = await client.post(
        f"/goals/{goal['id']}/contributions", headers=h,
        json={"from_account_id": str(acc.id), "amount_cents": 25_000, "occurred_on": "2026-11-12"},
    )  # fmt: skip
    assert c.status_code == 201
    assert (c.json()["type"], c.json()["goal_id"]) == ("transfer", goal["id"])
    got = (await client.get(f"/goals/{goal['id']}", headers=h)).json()
    assert (got["saved_cents"], got["target_cents"]) == (100_000, 120_000)
    assert isinstance(got["monthly_needed_cents"], int) and got["behind"] is False
    assert (await client.get(f"/accounts/{acc.id}", headers=h)).json()["balance_cents"] == 75_000
    w = await client.post(
        f"/goals/{goal['id']}/withdrawals", headers=h,
        json={"to_account_id": str(acc.id), "amount_cents": 5_000},
    )  # fmt: skip
    assert w.status_code == 201 and w.json()["counter_account_id"] == str(acc.id)
    listed = (await client.get(f"/spaces/{sp}/goals", headers=h)).json()
    assert [(g["id"], g["saved_cents"]) for g in listed] == [(goal["id"], 100_000)]
    over = await client.post(
        f"/goals/{goal['id']}/withdrawals", headers=h,
        json={"to_account_id": str(acc.id), "amount_cents": 20_001},
    )  # fmt: skip
    assert over.status_code == 422 and over.json() == {"detail": "insufficient_saved"}


async def test_goal_validation_and_access_over_http(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    ha, hb, sp = auth(a), auth(b), str(a.default_space_id)
    mine = await make_account(session, a.default_space_id)
    theirs = await make_account(session, b.default_space_id)
    for bad in (10.5, 0, "100"):
        r = await client.post(
            f"/spaces/{sp}/goals", json={"name": "x", "target_cents": bad}, headers=ha
        )
        assert r.status_code == 422, bad
    goal = (await client.post(f"/spaces/{sp}/goals", json={"name": "x", "target_cents": 1_000},
                              headers=ha)).json()  # fmt: skip
    assert (await client.post(f"/spaces/{sp}/goals", json={"name": "x", "target_cents": 100},
                              headers=hb)).status_code == 404  # fmt: skip
    assert (await client.get(f"/spaces/{sp}/goals", headers=hb)).status_code == 404
    assert (await client.get(f"/goals/{goal['id']}", headers=hb)).status_code == 404
    url = f"/goals/{goal['id']}/contributions"
    body = {"from_account_id": str(mine.id), "amount_cents": 100}
    assert (await client.post(url, json=body, headers=hb)).status_code == 404
    foreign = {"from_account_id": str(theirs.id), "amount_cents": 100}
    assert (await client.post(url, json=foreign, headers=ha)).status_code == 403
    floaty = {**body, "amount_cents": 10.5}
    assert (await client.post(url, json=floaty, headers=ha)).status_code == 422


async def test_goal_edit_and_delete_are_owner_only(client, session):
    from tests.factories import make_family

    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    fam = await make_family(session, a, b)
    r = await client.post(
        f"/spaces/{fam.id}/goals", headers=auth(b), json={"name": "Viagem", "target_cents": 1000}
    )
    assert r.status_code == 201  # membro pode criar
    gid = r.json()["id"]
    assert (
        await client.patch(f"/goals/{gid}", headers=auth(b), json={"name": "X"})
    ).status_code == 403
    assert (await client.delete(f"/goals/{gid}", headers=auth(b))).status_code == 403
    assert (
        await client.patch(f"/goals/{gid}", headers=auth(a), json={"name": "X"})
    ).status_code == 200
    assert (await client.delete(f"/goals/{gid}", headers=auth(a))).status_code == 204


async def test_goal_links_conflict_over_http(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    acc = await make_account(session, a.default_space_id)
    g1 = (
        await client.post(
            f"/spaces/{sp}/goals",
            headers=h,
            json={"name": "A", "target_cents": 1000, "account_ids": [str(acc.id)]},
        )
    ).json()
    r = await client.post(
        f"/spaces/{sp}/goals",
        headers=h,
        json={"name": "B", "target_cents": 1000, "account_ids": [str(acc.id)]},
    )
    assert r.status_code == 422 and r.json() == {"detail": "already_linked"}
    p = await client.patch(f"/goals/{g1['id']}", headers=h, json={"account_ids": []})
    assert p.status_code == 200 and p.json()["account_ids"] == []
