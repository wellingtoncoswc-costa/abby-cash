from datetime import date
from decimal import Decimal

from app.domain.pockets.models import CdiRate
from tests.factories import auth, make_account, make_user


async def test_pocket_flow_over_http(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    acc = await make_account(session, a.default_space_id, initial=100_000)
    r = await client.post(
        f"/spaces/{sp}/pockets",
        headers=h,
        json={"account_id": str(acc.id), "name": "Reserva", "cdi_bp": 12_000},
    )
    assert r.status_code == 201
    pk = r.json()
    assert (pk["balance_cents"], pk["pending_yield_cents"], pk["month_yield_cents"]) == (0, 0, 0)
    d = await client.post(f"/pockets/{pk['id']}/deposit", headers=h, json={"amount_cents": 60_000})
    assert d.status_code == 201 and d.json()["balance_cents"] == 60_000
    a_out = (await client.get(f"/accounts/{acc.id}", headers=h)).json()
    assert (a_out["balance_cents"], a_out["pockets_cents"], a_out["available_cents"]) == (
        100_000,
        60_000,
        40_000,
    )
    over = await client.post(
        f"/pockets/{pk['id']}/deposit", headers=h, json={"amount_cents": 40_001}
    )
    assert over.status_code == 409 and over.json() == {"detail": "insufficient_available"}
    w = await client.post(f"/pockets/{pk['id']}/withdraw", headers=h, json={"amount_cents": 10_000})
    assert w.status_code == 201 and w.json()["balance_cents"] == 50_000
    over = await client.post(
        f"/pockets/{pk['id']}/withdraw", headers=h, json={"amount_cents": 50_001}
    )
    assert over.status_code == 422
    mv = (await client.get(f"/pockets/{pk['id']}/movements", headers=h)).json()
    assert sorted(m["kind"] for m in mv) == ["deposit", "withdraw"]
    for bad in (0, 100_001, 1.5):
        r = await client.patch(f"/pockets/{pk['id']}", headers=h, json={"cdi_bp": bad})
        assert r.status_code == 422, bad
    r = await client.patch(
        f"/pockets/{pk['id']}", headers=h, json={"name": "Viagem", "cdi_bp": 11_000}
    )
    assert (r.json()["name"], r.json()["cdi_bp"]) == ("Viagem", 11_000)
    listed = (await client.get(f"/spaces/{sp}/pockets", headers=h)).json()
    assert [p["id"] for p in listed] == [pk["id"]]
    assert (await client.delete(f"/pockets/{pk['id']}", headers=h)).status_code == 422
    await client.post(f"/pockets/{pk['id']}/withdraw", headers=h, json={"amount_cents": 50_000})
    assert (await client.delete(f"/pockets/{pk['id']}", headers=h)).status_code == 204
    assert (await client.get(f"/spaces/{sp}/pockets", headers=h)).json() == []


async def test_pocket_isolation_between_spaces(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    ha, hb, sp = auth(a), auth(b), str(a.default_space_id)
    acc = await make_account(session, a.default_space_id, initial=1_000)
    theirs = await make_account(session, b.default_space_id)
    pk = (
        await client.post(
            f"/spaces/{sp}/pockets",
            headers=ha,
            json={"account_id": str(acc.id), "name": "x", "cdi_bp": 10_000},
        )
    ).json()
    assert (await client.get(f"/spaces/{sp}/pockets", headers=hb)).status_code == 404
    forbidden = await client.post(
        f"/spaces/{sp}/pockets",
        headers=hb,
        json={"account_id": str(acc.id), "name": "x", "cdi_bp": 1},
    )
    assert forbidden.status_code == 404
    for method, url, body in (
        ("POST", f"/pockets/{pk['id']}/deposit", {"amount_cents": 1}),
        ("POST", f"/pockets/{pk['id']}/withdraw", {"amount_cents": 1}),
        ("GET", f"/pockets/{pk['id']}/movements", None),
        ("PATCH", f"/pockets/{pk['id']}", {"name": "y"}),
        ("DELETE", f"/pockets/{pk['id']}", None),
    ):
        r = await client.request(method, url, headers=hb, json=body)
        assert r.status_code == 404, url
    # conta de outro espaço não vira caixinha neste
    r = await client.post(
        f"/spaces/{sp}/pockets",
        headers=ha,
        json={"account_id": str(theirs.id), "name": "x", "cdi_bp": 1},
    )
    assert r.status_code in (403, 404)
    assert (await client.get(f"/spaces/{sp}/pockets")).status_code == 401


async def test_cdi_latest(client, session):
    a = await make_user(session, "a@x.com")
    assert (await client.get("/cdi/latest", headers=auth(a))).status_code == 404
    session.add(CdiRate(on_date=date(2026, 11, 24), daily_pct=Decimal("0.055131")))
    await session.commit()
    r = (await client.get("/cdi/latest", headers=auth(a))).json()
    assert r["on_date"] == "2026-11-24" and r["daily_pct"] == "0.0551310000"
    assert r["annual_pct"].startswith("14.9")  # ((1+0,00055131)^252-1)*100 ~ 14,9


async def test_account_institution_validation(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    ok = await client.post(
        f"/spaces/{sp}/accounts",
        headers=h,
        json={"type": "checking", "name": "N", "institution": "nubank"},
    )
    assert ok.status_code == 201 and ok.json()["institution"] == "nubank"
    assert ok.json()["available_cents"] == 0
    for bad in ("Nu Bank", "", "x" * 41, "a-b"):
        r = await client.post(
            f"/spaces/{sp}/accounts",
            headers=h,
            json={"type": "checking", "name": "N", "institution": bad},
        )
        assert r.status_code == 422, bad
    p = await client.patch(f"/accounts/{ok.json()['id']}", headers=h, json={"institution": "itau"})
    assert p.json()["institution"] == "itau"
    p = await client.patch(f"/accounts/{ok.json()['id']}", headers=h, json={"institution": None})
    assert p.json()["institution"] is None
    listed = (await client.get("/accounts", headers=h)).json()
    assert "institution" in listed[0] and "pockets_cents" in listed[0]


async def test_loan_flow_and_isolation_over_http(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    ha, hb, sp = auth(a), auth(b), str(a.default_space_id)
    acc = await make_account(session, a.default_space_id, initial=1_000_000)
    body = {
        "kind": "consortium",
        "name": "Consórcio",
        "installment_cents": 50_000,
        "installments_total": 10,
        "first_due_on": "2026-01-31",
    }
    r = await client.post(f"/spaces/{sp}/loans", headers=ha, json=body)
    assert r.status_code == 201
    loan = r.json()
    assert (loan["paid_count"], loan["remaining_count"], loan["remaining_cents"]) == (
        0,
        10,
        500_000,
    )
    assert (loan["next_due_on"], loan["last_due_on"], loan["progress_pct"]) == (
        "2026-01-31",
        "2026-10-31",
        0,
    )
    bills = (await client.get(f"/spaces/{sp}/bills", headers=ha)).json()
    assert [(x["description"], x["due_on"]) for x in bills] == [
        ("Consórcio (1/10)", "2026-01-31"),
        ("Consórcio (2/10)", "2026-02-28"),
        ("Consórcio (3/10)", "2026-03-31"),
    ]
    assert bills[0]["loan_id"] == loan["id"] and bills[0]["installment_number"] == 1
    pay = await client.post(
        f"/bills/{bills[0]['id']}/payments", headers=ha, json={"account_id": str(acc.id)}
    )
    assert pay.status_code == 201
    got = (await client.get(f"/loans/{loan['id']}", headers=ha)).json()
    assert (got["paid_count"], got["remaining_cents"], got["progress_pct"]) == (1, 450_000, 10)
    locked = await client.delete(f"/bills/{bills[1]['id']}", headers=ha)
    assert locked.status_code == 422 and locked.json() == {"detail": "loan_bill_locked"}
    for bad in (0, 481):
        r = await client.post(
            f"/spaces/{sp}/loans", headers=ha, json=body | {"installments_total": bad}
        )
        assert r.status_code == 422
    assert (await client.get(f"/loans/{loan['id']}", headers=hb)).status_code == 404
    assert (await client.get(f"/spaces/{sp}/loans", headers=hb)).status_code == 404
    assert (await client.post(f"/spaces/{sp}/loans", headers=hb, json=body)).status_code == 404
    assert (
        await client.patch(f"/loans/{loan['id']}", headers=hb, json={"name": "x"})
    ).status_code == 404
    assert (await client.delete(f"/loans/{loan['id']}", headers=hb)).status_code == 404
    r = await client.patch(f"/loans/{loan['id']}", headers=ha, json={"installment_cents": 40_000})
    assert r.status_code == 200 and r.json()["remaining_cents"] == 40_000 * 9
    assert (await client.delete(f"/loans/{loan['id']}", headers=ha)).status_code == 204
    assert (await client.get(f"/spaces/{sp}/loans", headers=ha)).json() == []
    left = (await client.get(f"/spaces/{sp}/bills", headers=ha)).json()
    assert [x["status"] for x in left] == ["paid"]
