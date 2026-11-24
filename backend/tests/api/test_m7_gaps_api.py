from sqlalchemy import select

from app.domain.audit import AuditLog
from app.domain.users.models import SignupInvite
from tests.factories import (
    auth,
    category_id,
    make_account,
    make_card,
    make_family,
    make_link,
    make_user,
)


async def _post_tx(client, h, sp, acc, **kw):
    body = {"type": "expense", "amount_cents": 1000, "occurred_on": "2026-11-10",
            "account_id": str(acc.id)} | kw  # fmt: skip
    r = await client.post(f"/spaces/{sp}/transactions", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_me_and_settings(client, session):
    a = await make_user(session, "a@x.com")
    h = auth(a)
    me = (await client.get("/me", headers=h)).json()
    assert me["email"] == "a@x.com" and me["totp_enabled"] is False and me["is_admin"] is False
    assert "password_hash" not in me and "totp_secret" not in me
    assert (await client.get("/me")).status_code == 401
    ok = await client.patch("/me/settings", headers=h, json={
        "tz": "Europe/Lisbon", "reminder_time": "08:30", "weekly_digest": True})  # fmt: skip
    assert ok.status_code == 200
    got = ok.json()
    assert (got["tz"], got["reminder_time"], got["weekly_digest"]) == (
        "Europe/Lisbon",
        "08:30:00",
        True,
    )
    for bad in ({"tz": "Mars/Base"}, {"reminder_time": "25:00"}, {"weekly_digest": "yes"},
                {"tz": None}, {"preferred_channel": "telegram"},  # canal não vinculado
                {"default_space_id": "00000000-0000-0000-0000-000000000001"}):  # fmt: skip
        assert (await client.patch("/me/settings", headers=h, json=bad)).status_code == 422, bad
    await make_link(session, a)
    r = await client.patch("/me/settings", headers=h, json={"preferred_channel": "telegram"})
    assert r.json()["preferred_channel"] == "telegram"
    b = await make_user(session, "b@x.com")  # espaço alheio não vira default
    r = await client.patch(
        "/me/settings", headers=h, json={"default_space_id": str(b.default_space_id)}
    )
    assert r.status_code == 422
    acts = set(await session.scalars(select(AuditLog.action)))
    assert "user.update_settings" in acts


async def test_categories_crud_and_isolation(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    h, hb, sp = auth(a), auth(b), str(a.default_space_id)
    lst = (await client.get(f"/spaces/{sp}/categories", headers=h)).json()
    assert {c["name"] for c in lst} >= {"Mercado", "Outros"}
    assert (await client.get(f"/spaces/{sp}/categories", headers=hb)).status_code == 404
    r = await client.post(
        f"/spaces/{sp}/categories", headers=h, json={"name": "Café", "kind": "expense", "icon": "x"}
    )
    assert r.status_code == 201
    cid = r.json()["id"]
    dup = await client.post(
        f"/spaces/{sp}/categories", headers=h, json={"name": "café", "kind": "expense"}
    )
    assert (dup.status_code, dup.json()) == (422, {"detail": "category_exists"})
    assert (
        await client.post(
            f"/spaces/{sp}/categories", headers=h, json={"name": "Café", "kind": "income"}
        )
    ).status_code == 201
    assert (
        await client.post(
            f"/spaces/{sp}/categories", headers=h, json={"name": "x" * 61, "kind": "expense"}
        )
    ).status_code == 422
    assert (
        await client.patch(f"/categories/{cid}", headers=hb, json={"name": "Z"})
    ).status_code == 404
    assert (await client.patch(f"/categories/{cid}", headers=h, json={"name": "Cafeteria"})).json()[
        "name"
    ] == "Cafeteria"
    # em uso: recusa; reassign move
    acc = await make_account(session, a.default_space_id)
    await _post_tx(client, h, sp, acc, category_id=cid)
    r = await client.delete(f"/categories/{cid}", headers=h)
    assert (r.status_code, r.json()) == (422, {"detail": "category_in_use"})
    assert (await client.delete(f"/categories/{cid}", headers=hb)).status_code == 404
    outros = await category_id(session, a.default_space_id, "Outros")
    assert (
        await client.delete(f"/categories/{cid}?reassign_to={outros}", headers=h)
    ).status_code == 204
    txs = (await client.get(f"/spaces/{sp}/transactions", headers=h)).json()
    assert txs[0]["category_id"] == str(outros)
    assert (await client.delete(f"/categories/{outros}", headers=h)).status_code == 422
    inc = await category_id(session, a.default_space_id, "Salário", "income")
    free = await client.post(
        f"/spaces/{sp}/categories", headers=h, json={"name": "Livre", "kind": "expense"}
    )
    bad = await client.delete(f"/categories/{free.json()['id']}?reassign_to={inc}", headers=h)
    assert bad.status_code == 422  # tipo diferente
    assert (await client.delete(f"/categories/{free.json()['id']}", headers=h)).status_code == 204


async def test_transactions_patch_delete_filters(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    fam = await make_family(session, a, b)
    ha, hb, sp = auth(a), auth(b), str(fam.id)
    acc = await make_account(session, fam.id, initial=100_000)
    t1 = await _post_tx(client, ha, sp, acc, description="a1")
    t2 = await _post_tx(client, hb, sp, acc, description="b1")
    card = await make_card(session, a, fam.id)
    purchase = await client.post(f"/spaces/{sp}/card-purchases", headers=ha, json={
        "card_id": str(card.id), "amount_cents": 3000, "installments": 3,
        "occurred_on": "2026-11-10"})  # fmt: skip
    assert purchase.status_code == 201
    r = await client.get(f"/spaces/{sp}/transactions?limit=2", headers=ha)
    assert len(r.json()) == 2 and r.headers["x-total-count"] == "5"
    assert (await client.get(f"/spaces/{sp}/transactions?limit=201", headers=ha)).status_code == 422
    r = await client.get(f"/spaces/{sp}/transactions?created_by={b.id}", headers=ha)
    assert [t["id"] for t in r.json()] == [t2["id"]] and r.headers["x-total-count"] == "1"
    r = await client.get(f"/spaces/{sp}/transactions?card_id={card.id}", headers=ha)
    assert len(r.json()) == 3
    # autor-ou-dono: b não edita lançamento de a; dono (a) edita o de b
    assert (
        await client.patch(f"/transactions/{t1['id']}", headers=hb, json={"amount_cents": 5})
    ).status_code == 403
    assert (await client.delete(f"/transactions/{t1['id']}", headers=hb)).status_code == 403
    c = await make_user(session, "c@x.com")
    hc = auth(c)
    assert (
        await client.patch(f"/transactions/{t1['id']}", headers=hc, json={"description": "x"})
    ).status_code == 404
    assert (await client.delete(f"/transactions/{t1['id']}", headers=hc)).status_code == 404
    r = await client.patch(
        f"/transactions/{t2['id']}", headers=ha, json={"amount_cents": 2500, "description": "ok"}
    )
    assert (r.json()["amount_cents"], r.json()["description"]) == (2500, "ok")
    assert (
        await client.patch(f"/transactions/{t2['id']}", headers=ha, json={"amount_cents": 1.5})
    ).status_code == 422
    assert (await client.delete(f"/transactions/{t2['id']}", headers=ha)).status_code == 204
    # parcelada: apaga o grupo
    first = (await client.get(f"/spaces/{sp}/transactions?card_id={card.id}", headers=ha)).json()[0]
    assert (await client.delete(f"/transactions/{first['id']}", headers=ha)).status_code == 204
    left = await client.get(f"/spaces/{sp}/transactions?card_id={card.id}", headers=ha)
    assert left.json() == []
    acts = set(await session.scalars(select(AuditLog.action)))
    assert {"transaction.update", "transaction.delete"} <= acts


async def test_members_and_leave(client, session):
    a, b, c = [await make_user(session, f"{n}@x.com") for n in "abc"]
    fam = await make_family(session, a, b)
    ha, hb, hc, sp = auth(a), auth(b), auth(c), str(fam.id)
    r = await client.get(f"/spaces/{sp}/members", headers=hb)
    assert r.status_code == 200
    assert {(m["name"], m["role"]) for m in r.json()} == {
        ("a@x.com", "owner"),
        ("b@x.com", "member"),
    }
    assert all(set(m) == {"user_id", "name", "role", "joined_at"} for m in r.json())
    assert (await client.get(f"/spaces/{sp}/members", headers=hc)).status_code == 404
    assert (await client.delete(f"/spaces/{sp}/members/me", headers=hc)).status_code == 404
    r = await client.delete(f"/spaces/{sp}/members/me", headers=ha)
    assert (r.status_code, r.json()) == (422, {"detail": "owner_cannot_leave"})
    assert (await client.delete(f"/spaces/{sp}/members/me", headers=hb)).status_code == 204
    assert (await client.get(f"/spaces/{sp}/members", headers=hb)).status_code == 404
    assert "space.leave" in set(await session.scalars(select(AuditLog.action)))


async def test_account_card_edit_delete(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    fam = await make_family(session, a, b)
    ha, hb, hx = auth(a), auth(b), auth(await make_user(session, "x@x.com"))
    sp = str(fam.id)
    acc = await make_account(session, fam.id, name="Velha")
    r = await client.patch(
        f"/accounts/{acc.id}", headers=hb, json={"name": "Nova", "initial_balance_cents": 500}
    )
    assert (r.json()["name"], r.json()["initial_balance_cents"]) == ("Nova", 500)
    assert (
        await client.patch(f"/accounts/{acc.id}", headers=hx, json={"name": "H"})
    ).status_code == 404
    assert (await client.delete(f"/accounts/{acc.id}", headers=hx)).status_code == 404
    assert (await client.delete(f"/accounts/{acc.id}", headers=hb)).status_code == 403  # só dono
    used = await make_account(session, fam.id)
    await _post_tx(client, ha, sp, used)
    r = await client.delete(f"/accounts/{used.id}", headers=ha)
    assert (r.status_code, r.json()) == (422, {"detail": "account_in_use"})
    assert (await client.delete(f"/accounts/{acc.id}", headers=ha)).status_code == 204
    card = await make_card(session, a, fam.id)
    r = await client.patch(
        f"/cards/{card.id}", headers=hb, json={"name": "Master", "due_day": 5, "limit_cents": 9000}
    )
    assert (r.json()["name"], r.json()["due_day"], r.json()["limit_cents"]) == ("Master", 5, 9000)
    assert (await client.patch(f"/cards/{card.id}", headers=hb, json={"limit_cents": None})).json()[
        "limit_cents"
    ] is None
    assert (
        await client.patch(f"/cards/{card.id}", headers=hb, json={"due_day": 40})
    ).status_code == 422
    assert (
        await client.patch(f"/cards/{card.id}", headers=hx, json={"name": "H"})
    ).status_code == 404
    assert (await client.delete(f"/cards/{card.id}", headers=hb)).status_code == 403
    await client.post(f"/spaces/{sp}/card-purchases", headers=ha, json={
        "card_id": str(card.id), "amount_cents": 1000, "occurred_on": "2026-11-10"})  # fmt: skip
    r = await client.delete(f"/cards/{card.id}", headers=ha)
    assert (r.status_code, r.json()) == (422, {"detail": "card_in_use"})
    empty = await make_card(session, a, fam.id, name="Vazio")
    assert (await client.delete(f"/cards/{empty.id}", headers=ha)).status_code == 204
    acts = set(await session.scalars(select(AuditLog.action)))
    assert {"account.update", "account.delete", "card.update", "card.delete"} <= acts


async def test_bill_and_goal_edit_delete(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    h, hb, sp = auth(a), auth(b), str(a.default_space_id)
    acc = await make_account(session, a.default_space_id, initial=100_000)
    bill = (await client.post(f"/spaces/{sp}/bills", headers=h, json={
        "description": "Luz", "amount_cents": 5000, "due_on": "2026-12-10"})).json()  # fmt: skip
    r = await client.patch(
        f"/bills/{bill['id']}",
        headers=h,
        json={"amount_cents": 6000, "due_on": "2026-12-12", "description": "Luz+"},
    )
    assert (r.json()["amount_cents"], r.json()["due_on"]) == (6000, "2026-12-12")
    assert (
        await client.patch(f"/bills/{bill['id']}", headers=hb, json={"amount_cents": 1})
    ).status_code == 404
    assert (await client.delete(f"/bills/{bill['id']}", headers=hb)).status_code == 404
    assert (
        await client.patch(f"/bills/{bill['id']}", headers=h, json={"amount_cents": 0})
    ).status_code == 422
    paid = (await client.post(f"/spaces/{sp}/bills", headers=h, json={
        "description": "Net", "amount_cents": 3000, "due_on": "2026-12-10"})).json()  # fmt: skip
    await client.post(f"/bills/{paid['id']}/payments", headers=h, json={"account_id": str(acc.id)})
    for call in (client.patch(f"/bills/{paid['id']}", headers=h, json={"amount_cents": 1}),
                 client.delete(f"/bills/{paid['id']}", headers=h)):  # fmt: skip
        r = await call
        assert (r.status_code, r.json()) == (422, {"detail": "bill_not_editable"})
    assert (await client.delete(f"/bills/{bill['id']}", headers=h)).status_code == 204
    # metas
    goal = (
        await client.post(
            f"/spaces/{sp}/goals", headers=h, json={"name": "Viagem", "target_cents": 10000}
        )
    ).json()
    r = await client.patch(
        f"/goals/{goal['id']}",
        headers=h,
        json={"name": "Europa", "target_cents": 20000, "deadline": "2099-01-01"},
    )
    assert (r.json()["name"], r.json()["target_cents"], r.json()["saved_cents"]) == (
        "Europa",
        20000,
        0,
    )
    assert (
        await client.patch(f"/goals/{goal['id']}", headers=hb, json={"name": "H"})
    ).status_code == 404
    assert (await client.delete(f"/goals/{goal['id']}", headers=hb)).status_code == 404
    await client.post(
        f"/goals/{goal['id']}/contributions",
        headers=h,
        json={"from_account_id": str(acc.id), "amount_cents": 1000},
    )
    r = await client.delete(f"/goals/{goal['id']}", headers=h)
    assert (r.status_code, r.json()) == (422, {"detail": "goal_has_balance"})
    await client.post(
        f"/goals/{goal['id']}/withdrawals",
        headers=h,
        json={"to_account_id": str(acc.id), "amount_cents": 1000},
    )
    assert (await client.delete(f"/goals/{goal['id']}", headers=h)).json() == {
        "detail": "goal_has_history"
    }
    fresh = (
        await client.post(
            f"/spaces/{sp}/goals", headers=h, json={"name": "Nova", "target_cents": 100}
        )
    ).json()
    assert (await client.delete(f"/goals/{fresh['id']}", headers=h)).status_code == 204
    acts = set(await session.scalars(select(AuditLog.action)))
    assert {"bill.update", "bill.delete", "goal.update", "goal.delete"} <= acts


async def test_admin_signup_invite(client, session):
    a = await make_user(session, "a@x.com")
    assert (await client.post("/admin/signup-invites", headers=auth(a))).status_code == 403
    assert (await client.post("/admin/signup-invites")).status_code == 401
    a.is_admin = True
    await session.commit()
    r = await client.post("/admin/signup-invites", headers=auth(a))
    assert r.status_code == 201
    code = r.json()["code"]
    assert await session.scalar(select(SignupInvite.id).where(SignupInvite.code == code))
    reg = await client.post(
        "/auth/register",
        json={
            "email": "n@x.com",
            "name": "N",
            "password": "correct horse battery",
            "invite_code": code,
        },
    )
    assert reg.status_code == 201
    assert "signup_invite.create" in set(await session.scalars(select(AuditLog.action)))
