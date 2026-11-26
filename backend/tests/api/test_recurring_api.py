from tests.factories import auth, make_account, make_family, make_user


async def test_recurring_flow_over_http(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    acc = await make_account(session, a.default_space_id, name="Banco", initial=100_000)
    body = {
        "type": "income", "description": "Salário", "amount_cents": 500_000,
        "account_id": str(acc.id), "rule": {"kind": "monthly", "day": 5}, "starts_on": "2099-01-01",
    }  # fmt: skip
    r = await client.post(f"/spaces/{sp}/recurring", headers=h, json=body)
    assert r.status_code == 201 and r.json()["next_due_on"] == "2099-01-05"
    iid = r.json()["id"]
    assert [i["id"] for i in (await client.get(f"/spaces/{sp}/recurring", headers=h)).json()] == [
        iid
    ]
    p = await client.patch(
        f"/spaces/{sp}/recurring/{iid}", headers=h, json={"amount_cents": 600_000, "active": False}
    )
    assert p.status_code == 200 and p.json()["amount_cents"] == 600_000
    assert p.json()["active"] is False and p.json()["next_due_on"] is None
    proj = (await client.get(f"/spaces/{sp}/recurring/projection", headers=h)).json()
    assert len(proj["months"]) == 6 and proj["months"][0]["income_cents"] == 0  # pausado
    assert (await client.delete(f"/spaces/{sp}/recurring/{iid}", headers=h)).status_code == 204
    assert (await client.get(f"/spaces/{sp}/recurring", headers=h)).json() == []


async def test_recurring_validation_and_access(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    h, sp = auth(a), str(a.default_space_id)
    acc = await make_account(session, a.default_space_id)
    base = {"type": "expense", "description": "x", "amount_cents": 100, "account_id": str(acc.id),
            "rule": {"kind": "monthly", "day": 5}, "starts_on": "2026-11-01"}  # fmt: skip
    for bad in (
        {"amount_cents": 0},
        {"rule": {"kind": "monthly", "day": 40}},
        {"type": "transfer"},
        {"ends_on": "2026-10-01"},
    ):
        r = await client.post(f"/spaces/{sp}/recurring", headers=h, json={**base, **bad})
        assert r.status_code == 422, bad
    ok = await client.post(f"/spaces/{sp}/recurring", headers=h, json=base)
    assert ok.status_code == 201
    other = await client.get(f"/spaces/{sp}/recurring", headers=auth(b))
    assert other.status_code in (403, 404)
    fam = await make_family(session, a, b)
    facc = await make_account(session, fam.id)
    r = await client.post(
        f"/spaces/{fam.id}/recurring", headers=auth(b), json={**base, "account_id": str(facc.id)}
    )
    assert r.status_code in (403, 404)  # membro não-dono não cadastra
