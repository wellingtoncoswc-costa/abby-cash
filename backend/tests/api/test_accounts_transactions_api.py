from tests.factories import auth, category_id, make_account, make_family, make_user


async def _personal(client, headers) -> str:
    spaces = (await client.get("/spaces", headers=headers)).json()
    return next(s["id"] for s in spaces if s["type"] == "personal")


async def test_create_account_in_space_and_list(client, session):
    a = await make_user(session, "a@x.com")
    h = auth(a)
    sp = await _personal(client, h)
    r = await client.post(
        f"/spaces/{sp}/accounts",
        json={"type": "checking", "name": "Nubank", "initial_balance_cents": 10_000},
        headers=h,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["initial_balance_cents"] == 10_000 and isinstance(
        body["initial_balance_cents"], int
    )
    names = [x["name"] for x in (await client.get("/accounts", headers=h)).json()]
    assert names == ["Carteira", "Nubank"]
    bad = await client.post(f"/spaces/{sp}/accounts", json={"type": "pix", "name": "x"}, headers=h)
    assert bad.status_code == 422


async def test_family_space_gets_accounts_via_api(client, session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    r = await client.post(
        f"/spaces/{fam.id}/accounts", json={"type": "checking", "name": "Conjunta"},
        headers=auth(h),
    )  # fmt: skip
    assert r.status_code == 201 and r.json()["space_id"] == str(fam.id)
    assert "Conjunta" in [
        x["name"] for x in (await client.get("/accounts", headers=auth(w))).json()
    ]


async def test_transaction_roundtrip_amount_is_int_and_balance(client, session):
    a = await make_user(session, "a@x.com")
    h = auth(a)
    sp = str(a.default_space_id)
    acc = await make_account(session, a.default_space_id, initial=100_000)
    cat = await category_id(session, a.default_space_id)
    r = await client.post(
        f"/spaces/{sp}/transactions",
        json={"type": "expense", "amount_cents": 4_500, "occurred_on": "2026-11-10",
              "description": "feira", "category_id": str(cat), "account_id": str(acc.id)},
        headers=h,
    )  # fmt: skip
    assert r.status_code == 201
    assert r.json()["amount_cents"] == 4_500 and isinstance(r.json()["amount_cents"], int)
    listed = (await client.get(f"/spaces/{sp}/transactions?start=2026-11-01&end=2026-11-30",
                               headers=h)).json()  # fmt: skip
    assert [t["description"] for t in listed] == ["feira"]
    bal = (await client.get(f"/accounts/{acc.id}", headers=h)).json()
    assert bal["balance_cents"] == 95_500


async def test_amount_never_float_or_string(client, session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id)
    for bad in (45.5, "4500", 0, -1):
        r = await client.post(
            f"/spaces/{a.default_space_id}/transactions",
            json={"type": "expense", "amount_cents": bad, "account_id": str(acc.id)},
            headers=auth(a),
        )
        assert r.status_code == 422, bad


async def test_domain_error_is_422_with_code(client, session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id)
    r = await client.post(
        f"/spaces/{a.default_space_id}/transactions",
        json={"type": "transfer", "amount_cents": 100, "account_id": str(acc.id)},
        headers=auth(a),
    )
    assert r.status_code == 422 and r.json() == {"detail": "invalid_transfer"}


async def test_default_occurred_on_is_user_local_today(client, session):
    from app.core.dates import local_today

    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id)
    r = await client.post(
        f"/spaces/{a.default_space_id}/transactions",
        json={"type": "income", "amount_cents": 100, "account_id": str(acc.id)},
        headers=auth(a),
    )
    assert r.json()["occurred_on"] == local_today(a.tz).isoformat()


async def test_shared_account_403_and_non_member_404_over_http(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    theirs = await make_account(session, a.default_space_id)
    mine = await make_account(session, b.default_space_id)
    hb = auth(b)
    r = await client.post(
        f"/spaces/{b.default_space_id}/transactions",
        json={"type": "expense", "amount_cents": 100, "account_id": str(theirs.id)}, headers=hb,
    )  # fmt: skip
    assert r.status_code == 403
    sp_a = a.default_space_id
    assert (await client.post(f"/spaces/{sp_a}/accounts", json={"type": "wallet", "name": "x"},
                              headers=hb)).status_code == 404  # fmt: skip
    assert (await client.get(f"/accounts/{theirs.id}", headers=hb)).status_code == 404
    assert (await client.get(f"/spaces/{sp_a}/transactions", headers=hb)).status_code == 404
    assert (await client.post(
        f"/spaces/{sp_a}/transactions",
        json={"type": "expense", "amount_cents": 100, "account_id": str(mine.id)}, headers=hb,
    )).status_code == 404  # fmt: skip
    r = await client.put(
        f"/spaces/{sp_a}/default-account", json={"account_id": str(mine.id)}, headers=hb
    )
    assert r.status_code == 404
    assert (await client.get("/accounts")).status_code == 401


async def test_set_default_account(client, session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, name="Itaú")
    r = await client.put(
        f"/spaces/{a.default_space_id}/default-account", json={"account_id": str(acc.id)},
        headers=auth(a),
    )  # fmt: skip
    assert r.status_code == 204
    from app.domain.spaces.access import require_member

    assert (await require_member(session, a.id, a.default_space_id)).default_account_id == acc.id


async def test_amount_upper_bound_is_422_over_http(client, session):
    from app.core.money import MAX_CENTS

    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id)
    tx_url = f"/spaces/{a.default_space_id}/transactions"
    body = {"type": "income", "account_id": str(acc.id)}
    r = await client.post(tx_url, json=body | {"amount_cents": MAX_CENTS + 1}, headers=auth(a))
    assert r.status_code == 422
    r = await client.post(tx_url, json=body | {"amount_cents": MAX_CENTS}, headers=auth(a))
    assert r.status_code == 201
    acc_url = f"/spaces/{a.default_space_id}/accounts"
    for bal, code in ((MAX_CENTS + 1, 422), (-MAX_CENTS - 1, 422), (-MAX_CENTS, 201)):
        r = await client.post(
            acc_url, json={"type": "checking", "name": "x", "initial_balance_cents": bal},
            headers=auth(a),
        )  # fmt: skip
        assert r.status_code == code, bal


async def test_statement_over_http_aggregates_private(client, session):
    from datetime import date

    from app.domain.transactions.service import create_transaction

    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    acc = await make_account(session, fam.id, name="Conjunta")
    items = ((fam.id, 10_000, "mercado"), (w.default_space_id, 4_000, "segredo"))
    for space, amount, desc in items:
        await create_transaction(
            session, actor_id=w.id, space_id=space, type="expense", amount_cents=amount,
            occurred_on=date(2026, 11, 10), description=desc, account_id=acc.id,
        )  # fmt: skip
    url = f"/accounts/{acc.id}/statement?start=2026-11-01&end=2026-11-30"
    r = await client.get(url, headers=auth(h))
    assert r.status_code == 200
    body = r.json()
    assert [i["description"] for i in body["items"]] == ["mercado"]
    assert body["private_total_cents"] == -4_000 and body["total_cents"] == -14_000
    assert "segredo" not in r.text
    full = (await client.get(url, headers=auth(w))).json()
    assert len(full["items"]) == 2 and full["private_total_cents"] == 0
    stranger = await make_user(session, "z@x.com")
    assert (await client.get(url, headers=auth(stranger))).status_code == 404
