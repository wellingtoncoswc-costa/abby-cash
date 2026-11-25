from datetime import date

from app.domain.cards.service import register_card_purchase
from tests.factories import auth, category_id, make_account, make_card, make_user


async def _bill(client, headers, space, **kw):
    body = {"description": "Luz", "amount_cents": 12_000, "due_on": "2026-11-20"} | kw
    r = await client.post(f"/spaces/{space}/bills", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_bill_with_recurrence_and_payment_over_http(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    acc = await make_account(session, a.default_space_id, initial=50_000)
    cat = str(await category_id(session, a.default_space_id, "Contas da casa"))
    bill = await _bill(
        client, h, sp, category_id=cat, recurrence={"kind": "monthly", "day": 31},
        responsible_user_id=str(a.id),
    )  # fmt: skip
    assert bill["amount_cents"] == 12_000 and isinstance(bill["amount_cents"], int)
    assert bill["recurrence_rule"]["day"] == 31 and bill["status"] == "open"
    no_acc = await client.post(f"/bills/{bill['id']}/payments", json={}, headers=h)
    assert no_acc.status_code == 422  # conta de origem obrigatória (corpo)
    r = await client.post(
        f"/bills/{bill['id']}/payments",
        json={"account_id": str(acc.id), "amount_cents": 5_000, "paid_on": "2026-11-18"},
        headers=h,
    )  # fmt: skip
    assert r.status_code == 201
    tx = r.json()
    assert (tx["type"], tx["amount_cents"], tx["bill_id"]) == ("expense", 5_000, bill["id"])
    listed = (await client.get(f"/spaces/{sp}/bills?status=partial", headers=h)).json()
    assert [b["id"] for b in listed] == [bill["id"]]
    bal = (await client.get(f"/accounts/{acc.id}", headers=h)).json()["balance_cents"]
    assert bal == 45_000


async def test_invoice_payment_over_http(client, session):
    a = await make_user(session, "a@x.com")
    h = auth(a)
    acc = await make_account(session, a.default_space_id, initial=100_000)
    card = await make_card(session, a, a.default_space_id)
    (buy,) = await register_card_purchase(
        session, actor_id=a.id, space_id=a.default_space_id, card_id=card.id,
        amount_cents=30_000, occurred_on=date(2026, 11, 5),
    )  # fmt: skip
    url = f"/invoices/{buy.invoice_id}/payments"
    r = await client.post(
        url, json={"account_id": str(acc.id), "amount_cents": 10_000, "paid_on": "2026-11-18"},
        headers=h,
    )  # fmt: skip
    assert r.status_code == 201 and r.json()["type"] == "transfer"
    inv = (await client.get(f"/invoices/{buy.invoice_id}", headers=h)).json()
    got = (inv["total_cents"], inv["paid_cents"], inv["remaining_cents"])
    assert got == (30_000, 10_000, 20_000)
    assert inv["status"] == "partial"
    body = {"account_id": str(acc.id), "amount_cents": 20_001}
    over = await client.post(url, json=body, headers=h)
    assert over.status_code == 422 and over.json() == {"detail": "invalid_payment_amount"}
    missing = await client.post(url, json={"amount_cents": 100}, headers=h)
    assert missing.status_code == 422
    manual_bill = await client.post(
        f"/bills/{inv['id']}/payments", json={"account_id": str(acc.id)}, headers=h
    )  # id de fatura não é conta
    assert manual_bill.status_code == 404


async def test_bill_validation_422(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    base = {"description": "Luz", "amount_cents": 100, "due_on": "2026-11-20"}
    for bad in (
        {"amount_cents": 10.5}, {"amount_cents": 0}, {"recurrence": {"kind": "monthly", "day": 32}},
        {"recurrence": {"kind": "every_n_months", "day": 5, "n": 10**9}},
        {"recurrence": {"kind": "yearly", "day": 5}}, {"recurrence": {"kind": "weekly", "day": 5}},
    ):  # fmt: skip
        r = await client.post(f"/spaces/{sp}/bills", json=base | bad, headers=h)
        assert r.status_code == 422, bad


async def test_bills_routes_404_for_non_member_and_403_for_foreign_account(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    ha, hb = auth(a), auth(b)
    sp_a = str(a.default_space_id)
    bill = await _bill(client, ha, sp_a)
    mine = await make_account(session, b.default_space_id)
    theirs = await make_account(session, a.default_space_id)
    body = {"description": "x", "amount_cents": 1, "due_on": "2026-11-20"}
    assert (await client.post(f"/spaces/{sp_a}/bills", json=body, headers=hb)).status_code == 404
    assert (await client.get(f"/spaces/{sp_a}/bills", headers=hb)).status_code == 404
    pay = await client.post(
        f"/bills/{bill['id']}/payments", json={"account_id": str(mine.id)}, headers=hb
    )
    assert pay.status_code == 404
    pay = await client.post(
        f"/bills/{bill['id']}/payments", json={"account_id": str(theirs.id)}, headers=hb
    )
    assert pay.status_code == 404  # b nem enxerga a conta a pagar: 404 vem antes do 403
    card = await make_card(session, a, a.default_space_id)
    (buy,) = await register_card_purchase(
        session, actor_id=a.id, space_id=a.default_space_id, card_id=card.id, amount_cents=100,
        occurred_on=date(2026, 11, 5),
    )  # fmt: skip
    pay = await client.post(
        f"/invoices/{buy.invoice_id}/payments",
        json={"account_id": str(mine.id), "amount_cents": 1}, headers=hb,
    )  # fmt: skip
    assert pay.status_code == 404
    # a tenta pagar com a conta do b: 403
    pay = await client.post(
        f"/bills/{bill['id']}/payments", json={"account_id": str(mine.id)}, headers=ha
    )
    assert pay.status_code == 403


async def test_delete_series_over_http(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    bill = await _bill(client, h, sp, recurrence={"kind": "monthly", "day": 20})
    assert (await client.delete(f"/bills/{bill['id']}?series=true", headers=h)).status_code == 204
    assert (await client.get(f"/spaces/{sp}/bills", headers=h)).json() == []
    b = await make_user(session, "b@x.com")
    other = await _bill(client, h, sp, recurrence={"kind": "monthly", "day": 20})
    r = await client.delete(f"/bills/{other['id']}?series=true", headers=auth(b))
    assert r.status_code == 404
