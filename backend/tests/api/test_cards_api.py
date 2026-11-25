from datetime import UTC, datetime

from app.core.dates import to_local_date
from tests.factories import auth, make_card, make_family, make_user


async def _new_card(client, headers, space, **kw):
    body = {"name": "Visa", "closing_day": 10, "due_day": 20} | kw
    r = await client.post(f"/spaces/{space}/cards", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_card_purchase_installments_over_http(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    card = await _new_card(client, h, sp, limit_cents=500_000)
    assert card["limit_cents"] == 500_000
    r = await client.post(
        f"/spaces/{sp}/card-purchases",
        json={"card_id": card["id"], "amount_cents": 1_000, "installments": 3,
              "occurred_on": "2026-11-05", "description": "tv"},
        headers=h,
    )  # fmt: skip
    assert r.status_code == 201
    txs = r.json()
    assert [t["amount_cents"] for t in txs] == [334, 333, 333]
    assert all(isinstance(t["amount_cents"], int) for t in txs)
    invs = (await client.get(f"/cards/{card['id']}/invoices", headers=h)).json()
    assert [i["due_on"] for i in invs] == ["2027-01-20", "2026-12-20", "2026-11-20"]
    assert [i["total_cents"] for i in invs] == [333, 333, 334]
    detail = (await client.get(f"/invoices/{txs[0]['invoice_id']}", headers=h)).json()
    assert detail["total_cents"] == 334 and detail["paid_cents"] == 0
    assert detail["remaining_cents"] == 334 and detail["status"] == "open"
    assert [i["amount_cents"] for i in detail["statement"]["items"]] == [334]
    assert detail["statement"]["private_total_cents"] == 0
    assert [c["id"] for c in (await client.get("/cards", headers=h)).json()] == [card["id"]]


async def test_card_and_purchase_validation_422(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    for bad in ({"closing_day": 0}, {"closing_day": 32}, {"due_day": "10"}, {"limit_cents": 9.5}):
        r = await client.post(
            f"/spaces/{sp}/cards", json={"name": "V", "closing_day": 10, "due_day": 20} | bad,
            headers=h,
        )  # fmt: skip
        assert r.status_code == 422, bad
    card = await _new_card(client, h, sp)
    base = {"card_id": card["id"], "amount_cents": 1_000, "occurred_on": "2026-11-05"}
    for bad in ({"installments": 0}, {"installments": 49}, {"amount_cents": 10.5}):
        r = await client.post(f"/spaces/{sp}/card-purchases", json=base | bad, headers=h)
        assert r.status_code == 422, bad
    r = await client.post(
        f"/spaces/{sp}/card-purchases", json=base | {"amount_cents": 2, "installments": 3},
        headers=h,
    )  # fmt: skip
    assert r.status_code == 422 and r.json() == {"detail": "amount_too_small"}


async def test_purchase_without_date_uses_user_local_date(client, session, monkeypatch):
    # 02:30 UTC de 11/03 = 23:30 de 10/03 em São Paulo (dia do fechamento)
    instant = datetime(2026, 3, 11, 2, 30, tzinfo=UTC)
    monkeypatch.setattr("app.api.cards.local_today", lambda tz: to_local_date(instant, tz))
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    card = await _new_card(client, h, sp)
    r = await client.post(
        f"/spaces/{sp}/card-purchases", json={"card_id": card["id"], "amount_cents": 1_000},
        headers=h,
    )  # fmt: skip
    tx = r.json()[0]
    assert tx["occurred_on"] == "2026-03-10"
    inv = (await client.get(f"/invoices/{tx['invoice_id']}", headers=h)).json()
    assert inv["closing_on"] == "2026-03-10" and inv["due_on"] == "2026-03-20"


async def test_cards_routes_404_for_non_member_and_403_for_foreign_card(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    card = await make_card(session, a, a.default_space_id)
    ha, hb = auth(a), auth(b)
    sp_a = str(a.default_space_id)
    r = await client.post(
        f"/spaces/{sp_a}/card-purchases",
        json={"card_id": str(card.id), "amount_cents": 1_000, "occurred_on": "2026-11-05"},
        headers=ha,
    )  # fmt: skip
    inv_id = r.json()[0]["invoice_id"]
    assert (await client.post(f"/spaces/{sp_a}/cards", json={"name": "V", "closing_day": 1,
                              "due_day": 2}, headers=hb)).status_code == 404  # fmt: skip
    assert (await client.get(f"/cards/{card.id}/invoices", headers=hb)).status_code == 404
    assert (await client.get(f"/invoices/{inv_id}", headers=hb)).status_code == 404
    assert (await client.get("/cards", headers=hb)).json() == []
    r = await client.post(
        f"/spaces/{b.default_space_id}/card-purchases",
        json={"card_id": str(card.id), "amount_cents": 1_000, "occurred_on": "2026-11-05"},
        headers=hb,
    )  # fmt: skip
    assert r.status_code == 403
    assert (await client.get("/cards")).status_code == 401


async def test_shared_invoice_hides_private_items_over_http(client, session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    card = await make_card(session, w, fam.id)
    body = {"card_id": str(card.id), "occurred_on": "2026-11-05"}
    await client.post(f"/spaces/{fam.id}/card-purchases",
                      json=body | {"amount_cents": 10_000, "description": "mercado"},
                      headers=auth(w))  # fmt: skip
    r = await client.post(f"/spaces/{w.default_space_id}/card-purchases",
                          json=body | {"amount_cents": 4_000, "description": "segredo"},
                          headers=auth(w))  # fmt: skip
    inv_id = r.json()[0]["invoice_id"]
    seen = await client.get(f"/invoices/{inv_id}", headers=auth(h))
    assert "segredo" not in seen.text
    st = seen.json()["statement"]
    assert [i["description"] for i in st["items"]] == ["mercado"]
    assert st["private_total_cents"] == 4_000 and st["total_cents"] == 14_000
    assert seen.json()["total_cents"] == 14_000
