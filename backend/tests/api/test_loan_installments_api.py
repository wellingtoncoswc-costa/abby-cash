import io
import json
import time
import zipfile
from datetime import date

from sqlalchemy import func, select

from app.domain.audit import AuditLog
from app.domain.bills.models import Bill
from app.domain.transactions.models import Transaction
from app.domain.transactions.service import account_balance
from tests.factories import auth, make_account, make_user

BODY = {
    "kind": "financing", "name": "Carro", "installment_cents": 100_000,
    "installments_total": 12, "first_due_on": "2026-12-10",
}  # fmt: skip


async def _mk(client, h, sp, **kw):
    r = await client.post(f"/spaces/{sp}/loans", headers=h, json=BODY | kw)
    assert r.status_code == 201, r.text
    return r.json()


async def _states(client, h, loan_id):
    r = await client.get(f"/loans/{loan_id}/installments", headers=h)
    assert r.status_code == 200
    return [(i["number"], i["state"]) for i in r.json()], r.json()


async def test_create_with_paid_installments_and_lazy_generation(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    for bad in (-1, 13, 1.5):
        r = await client.post(
            f"/spaces/{sp}/loans", headers=h, json=BODY | {"paid_installments": bad}
        )
        assert r.status_code == 422, bad
    zero = await _mk(client, h, sp)
    assert (zero["paid_count"], zero["remaining_cents"]) == (0, 1_200_000)
    mid = await _mk(client, h, sp, name="Meio", paid_installments=5)
    assert (mid["paid_count"], mid["remaining_count"], mid["remaining_cents"]) == (5, 7, 700_000)
    assert (mid["progress_pct"], mid["next_due_on"]) == (41, "2027-05-10")
    rows = (
        await session.scalars(
            select(Bill).where(Bill.loan_id == mid["id"]).order_by(Bill.installment_number)
        )
    ).all()
    got_rows = [(b.installment_number, b.status, b.settled_historical_at is not None) for b in rows]
    assert got_rows == [
        *[(n, "paid", True) for n in range(1, 6)], *[(n, "open", False) for n in (6, 7, 8)],
    ]  # fmt: skip
    full = await _mk(client, h, sp, name="Tudo", paid_installments=12)
    assert (full["paid_count"], full["remaining_count"], full["remaining_cents"]) == (12, 0, 0)
    assert (full["progress_pct"], full["next_due_on"]) == (100, None)
    open_bills = (await client.get(f"/spaces/{sp}/bills?status=open", headers=h)).json()
    assert sorted(b["description"] for b in open_bills if b["loan_id"] != zero["id"]) == [
        "Meio (6/12)", "Meio (7/12)", "Meio (8/12)",
    ]  # fmt: skip
    assert await session.scalar(select(func.count()).select_from(Transaction)) == 0


async def test_historical_has_no_money_effect_and_is_not_open_anywhere(client, session):
    from app.jobs.digest import build_digest

    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    acc = await make_account(session, a.default_space_id, initial=500_000)
    loan = await _mk(client, h, sp, first_due_on="2026-11-25", installments_total=3)
    before = await account_balance(session, acc.id)
    r = await client.post(f"/loans/{loan['id']}/installments/1/settle", headers=h)
    assert r.status_code == 200 and r.json()["state"] == "paid_history"
    again = await client.post(f"/loans/{loan['id']}/installments/1/settle", headers=h)
    assert again.json() == r.json()
    assert await account_balance(session, acc.id) == before
    assert await session.scalar(select(func.count()).select_from(Transaction)) == 0
    got = (await client.get(f"/loans/{loan['id']}", headers=h)).json()
    assert (got["paid_count"], got["remaining_cents"], got["progress_pct"]) == (1, 200_000, 33)
    open_ = (await client.get(f"/spaces/{sp}/bills?status=open", headers=h)).json()
    assert [b["installment_number"] for b in open_] == [2, 3]
    digest = await build_digest(session, a.id, date(2026, 11, 24))
    assert "Carro (1/3)" not in digest
    ov = await client.get(
        f"/spaces/{sp}/reports/overview?start=2026-11-01&end=2026-11-30", headers=h
    )
    assert ov.status_code == 200
    assert all("(1/3)" not in u["description"] for u in ov.json()["upcoming"])
    # a baixa histórica não é paga duas vezes
    bill_id = (await client.get(f"/loans/{loan['id']}/installments", headers=h)).json()[0][
        "bill_id"
    ]
    p = await client.post(f"/bills/{bill_id}/payments", headers=h, json={"account_id": str(acc.id)})
    assert p.status_code == 422 and p.json() == {"detail": "bill_already_paid"}
    logs = await session.scalars(
        select(AuditLog.action).where(AuditLog.action.like("loan.installment%"))
    )
    assert list(logs) == ["loan.installment_settle"]  # idempotente: um só registro


async def test_unsettle_and_real_payment_conflict(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    acc = await make_account(session, a.default_space_id, initial=500_000)
    loan = await _mk(client, h, sp)
    lid = loan["id"]
    await client.post(f"/loans/{lid}/installments/1/settle", headers=h)
    d = await client.delete(f"/loans/{lid}/installments/1/settle", headers=h)
    assert d.status_code == 200 and d.json()["state"] == "open" and d.json()["bill_id"]
    assert (
        await client.delete(f"/loans/{lid}/installments/1/settle", headers=h)
    ).status_code == 200
    got = (await client.get(f"/loans/{lid}", headers=h)).json()
    assert (got["paid_count"], got["remaining_cents"]) == (0, 1_200_000)
    bill_id = d.json()["bill_id"]
    pay = await client.post(
        f"/bills/{bill_id}/payments", headers=h, json={"account_id": str(acc.id)}
    )
    assert pay.status_code == 201
    st, _ = await _states(client, h, lid)
    assert st[0] == (1, "paid_real")
    for method in ("post", "delete"):
        r = await getattr(client, method)(f"/loans/{lid}/installments/1/settle", headers=h)
        assert r.status_code == 409 and r.json() == {"detail": "installment_paid_real"}
    # excluir o lançamento reabre a parcela
    tx = await session.scalar(select(Transaction.id))
    assert (await client.delete(f"/transactions/{tx}", headers=h)).status_code == 204
    st, _ = await _states(client, h, lid)
    assert st[0] == (1, "open")
    assert (await client.post(f"/loans/{lid}/installments/13/settle", headers=h)).status_code == 422
    assert (await client.post(f"/loans/{lid}/installments/0/settle", headers=h)).status_code == 422


async def test_far_installment_materialize_and_checklist(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    loan = await _mk(client, h, sp, installments_total=360, first_due_on="2026-01-31")
    lid = loan["id"]
    st, items = await _states(client, h, lid)
    assert len(items) == 360 and {s for _, s in st} == {"open"}
    assert items[199]["due_on"] == "2042-08-31" and items[199]["bill_id"] is None
    assert items[0]["bill_id"] and items[3]["bill_id"] is None
    r = await client.post(f"/loans/{lid}/installments/200/settle", headers=h)
    assert r.json()["state"] == "paid_history" and r.json()["due_on"] == "2042-08-31"
    got = (await client.get(f"/loans/{lid}", headers=h)).json()
    assert (got["paid_count"], got["remaining_count"]) == (1, 359)
    assert got["remaining_cents"] == 359 * 100_000 and got["next_due_on"] == "2026-01-31"
    n = await session.scalar(select(func.count()).select_from(Bill).where(Bill.loan_id == lid))
    assert n == 4  # 1-3 + 200; o vão não é preenchido
    m = await client.post(f"/loans/{lid}/installments/150/materialize", headers=h)
    assert m.status_code == 200 and m.json()["installment_number"] == 150
    again = await client.post(f"/loans/{lid}/installments/150/materialize", headers=h)
    assert again.json()["id"] == m.json()["id"]
    # pagar #1 gera a #4 (primeiras 3 não pagas), não a #201
    acc = await make_account(session, a.default_space_id, initial=500_000)
    b1 = (await _states(client, h, lid))[1][0]["bill_id"]
    await client.post(f"/bills/{b1}/payments", headers=h, json={"account_id": str(acc.id)})
    nums = list(
        await session.scalars(
            select(Bill.installment_number)
            .where(Bill.loan_id == lid)
            .order_by(Bill.installment_number)
        )
    )
    assert nums == [1, 2, 3, 4, 150, 200]


async def test_isolation_and_480_performance(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    ha, hb, sp = auth(a), auth(b), str(a.default_space_id)
    t0 = time.monotonic()
    loan = await _mk(client, ha, sp, installments_total=480, paid_installments=479)
    items = (await client.get(f"/loans/{loan['id']}/installments", headers=ha)).json()
    assert time.monotonic() - t0 < 10 and len(items) == 480
    assert (loan["paid_count"], loan["remaining_count"], loan["next_due_on"]) == (
        479,
        1,
        "2066-11-10",
    )
    lid = loan["id"]
    for method, path in (
        ("get", "installments"), ("post", "installments/1/settle"),
        ("delete", "installments/1/settle"), ("post", "installments/1/materialize"),
    ):  # fmt: skip
        assert (
            await getattr(client, method)(f"/loans/{lid}/{path}", headers=hb)
        ).status_code == 404
    st, _ = await _states(client, ha, lid)
    assert st[0] == (1, "paid_history") and st[-1] == (480, "open")
    await client.delete(f"/loans/{lid}", headers=ha)
    assert (
        await client.post(f"/loans/{lid}/installments/480/settle", headers=ha)
    ).status_code == 422


async def test_export_has_settled_field(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), str(a.default_space_id)
    await _mk(client, h, sp, paid_installments=1)
    r = await client.get("/privacy/export", headers=h)
    data = json.loads(zipfile.ZipFile(io.BytesIO(r.content)).read("data.json"))
    assert sum(1 for x in data["bills"] if x["settled_historical_at"]) == 1
