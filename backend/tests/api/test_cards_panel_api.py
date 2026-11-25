from tests.factories import auth, make_card, make_user


async def test_panel_and_invoice_total_over_http(client, session):
    a = await make_user(session, "a@x.com")
    h = auth(a)
    card = await make_card(
        session, a, a.default_space_id, closing_day=10, due_day=20, limit_cents=50_000
    )
    r = await client.post(
        f"/cards/{card.id}/invoice-totals", headers=h,
        json={"month": "2026-08", "total_cents": 12_000},
    )  # fmt: skip
    assert r.status_code == 201
    assert (r.json()["closing_on"], r.json()["total_cents"]) == ("2026-08-10", 12_000)
    p = (await client.get(f"/cards/{card.id}/panel", headers=h)).json()
    assert p["used_cents"] == 12_000 and p["available_cents"] == 38_000
    assert p["invoice"]["id"] == r.json()["id"] and p["history"][0]["total_cents"] == 12_000
    sel = await client.get(f"/cards/{card.id}/panel?invoice={r.json()['id']}", headers=h)
    assert sel.status_code == 200
    bad = await client.post(
        f"/cards/{card.id}/invoice-totals", headers=h, json={"month": "2026-13", "total_cents": 1}
    )
    assert bad.status_code == 422
    zero = await client.post(
        f"/cards/{card.id}/invoice-totals", headers=h, json={"month": "2026-08", "total_cents": 0}
    )
    assert zero.status_code == 422


async def test_panel_requires_membership(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    card = await make_card(session, a, a.default_space_id)
    r = await client.get(f"/cards/{card.id}/panel", headers=auth(b))
    assert r.status_code in (403, 404)
