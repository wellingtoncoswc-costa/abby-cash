import csv
import io
import json
import zipfile
from datetime import date

from sqlalchemy import func, select

from app.domain.accounts.models import Account
from app.domain.bills.models import Bill
from app.domain.bills.service import create_bill
from app.domain.budgets.models import Budget, BudgetAlertSent
from app.domain.budgets.service import evaluate_thresholds, set_budget
from app.domain.cards.models import CreditCard, Invoice
from app.domain.cards.service import register_card_purchase
from app.domain.categories.models import Category
from app.domain.goals.models import Goal
from app.domain.goals.service import contribute, create_goal
from app.domain.payments import pay_bill
from app.domain.spaces.models import Space, SpaceMember
from app.domain.transactions.models import Transaction
from app.domain.transactions.service import create_transaction, list_transactions
from app.domain.users.models import User
from tests.factories import PWD, auth, make_account, make_card, make_family, make_user

D = date(2026, 11, 10)


async def _tx(session, user, space, acc, amount, desc):
    return await create_transaction(
        session, actor_id=user.id, space_id=space, type="expense", amount_cents=amount,
        occurred_on=D, description=desc, account_id=acc.id,
    )  # fmt: skip


async def _delete(client, user, password=PWD):
    return await client.request(
        "DELETE", "/privacy/account", json={"password": password}, headers=auth(user)
    )


async def test_export_contains_only_user_spaces(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    fam = await make_family(session, a, b)
    acc_a = await make_account(session, a.default_space_id, name="Itaú")
    acc_b = await make_account(session, b.default_space_id, name="Nubank do b")
    acc_f = await make_account(session, fam.id, name="Conjunta")
    await _tx(session, a, a.default_space_id, acc_a, 1_000, "meu-gasto")
    await _tx(session, b, fam.id, acc_f, 2_000, "gasto-familia")
    await _tx(session, b, b.default_space_id, acc_b, 3_000, "gasto-do-b")
    r = await client.get("/privacy/export", headers=auth(a))
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(z.namelist()) == ["data.json", "transactions.csv"]
    raw = z.read("data.json").decode()
    data = json.loads(raw)
    assert {t["description"] for t in data["transactions"]} == {"meu-gasto", "gasto-familia"}
    assert {s["id"] for s in data["spaces"]} == {str(a.default_space_id), str(fam.id)}
    assert all(isinstance(t["amount_cents"], int) for t in data["transactions"])
    assert data["user"]["email"] == "a@x.com"
    assert "gasto-do-b" not in raw and "Nubank do b" not in raw and "b@x.com" not in raw
    rows = list(csv.DictReader(io.StringIO(z.read("transactions.csv").decode())))
    assert sorted(x["description"] for x in rows) == ["gasto-familia", "meu-gasto"]
    assert {x["amount_cents"] for x in rows} == {"1000", "2000"}


async def test_export_and_delete_require_auth(client):
    assert (await client.get("/privacy/export")).status_code == 401
    r = await client.request("DELETE", "/privacy/account", json={"password": PWD})
    assert r.status_code == 401


async def test_delete_account_requires_password(client, session):
    a = await make_user(session, "a@x.com")
    r = await _delete(client, a, "senha errada aqui")
    assert r.status_code == 401 and r.json() == {"detail": "invalid_credentials"}
    assert await session.scalar(select(func.count()).select_from(User).where(User.id == a.id)) == 1


async def test_delete_account_anonymizes_family_transactions(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    a_id, b_id, pa = a.id, b.id, a.default_space_id
    fam = await make_family(session, b, a)  # b é dono; a é membro
    fam_id = fam.id
    acc_a = await make_account(session, pa, name="Itaú", initial=100_000)
    acc_f = await make_account(session, fam_id, name="Conjunta")
    card = await make_card(session, a, pa)
    await register_card_purchase(
        session, actor_id=a_id, space_id=pa, card_id=card.id, amount_cents=6_000, occurred_on=D
    )  # fmt: skip
    goal = await create_goal(
        session, actor_id=a_id, space_id=pa, name="Viagem", target_cents=9_000, created_on=D
    )  # fmt: skip
    await contribute(
        session, actor_id=a_id, goal_id=goal.id, from_account_id=acc_a.id, amount_cents=1_000, on=D
    )  # fmt: skip
    bill = await create_bill(
        session, actor_id=a_id, space_id=pa, description="Luz", amount_cents=2_000, due_on=D
    )  # fmt: skip
    await pay_bill(session, actor_id=a_id, bill_id=bill.id, account_id=acc_a.id, paid_on=D)
    await set_budget(session, actor_id=a_id, space_id=pa, month=D, limit_cents=5_000)
    assert await evaluate_thresholds(session, pa, D)  # grava alertas enviados
    await _tx(session, a, fam_id, acc_f, 3_000, "gasto-familia")
    await _tx(session, a, fam_id, acc_a, 700, "pelo-pessoal")  # família, mas na conta pessoal do a
    await _tx(session, b, fam_id, acc_f, 900, "gasto-do-b")

    ha = auth(a)  # antes do expire_all: depois disso `a.id` não pode mais ser lido
    r = await _delete(client, a)
    assert r.status_code == 204

    session.expire_all()  # o servidor usou outra sessão
    count = lambda model, *where: session.scalar(  # noqa: E731
        select(func.count()).select_from(model).where(*where)
    )
    assert await count(User, User.id == a_id) == 0
    assert await count(Space, Space.id == pa) == 0
    for model in (Account, Category, CreditCard, Bill, Goal, Budget, BudgetAlertSent, Transaction):
        assert await count(model, model.space_id == pa) == 0, model.__name__
    assert await count(Invoice) == 0  # as faturas do cartão pessoal foram junto
    assert await count(SpaceMember, SpaceMember.user_id == a_id) == 0
    assert await count(Space, Space.id == fam_id) == 1  # a família continua com o b
    txs = {
        t.description: t for t in await list_transactions(session, viewer_id=b_id, space_id=fam_id)
    }
    assert set(txs) == {"gasto-familia", "pelo-pessoal", "gasto-do-b"}
    assert txs["gasto-familia"].created_by is None and txs["gasto-familia"].amount_cents == 3_000
    assert txs["pelo-pessoal"].created_by is None and txs["pelo-pessoal"].account_id is None
    assert txs["gasto-do-b"].created_by == b_id
    assert (await client.get("/spaces", headers=ha)).status_code == 401  # o token morreu junto


async def test_delete_refused_when_owning_family_with_members(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    fam = await make_family(session, a, b)
    r = await _delete(client, a)
    assert r.status_code == 422 and r.json() == {"detail": "owns_family_with_members"}
    assert await session.scalar(select(func.count()).select_from(User).where(User.id == a.id)) == 1
    assert (
        await session.scalar(select(func.count()).select_from(Space).where(Space.id == fam.id)) == 1
    )


async def test_delete_removes_solo_family_owned_by_user(client, session):
    a = await make_user(session, "a@x.com")
    a_id = a.id
    from app.domain.spaces.service import create_family_space

    fam = await create_family_space(session, owner_id=a_id, name="Só eu")
    fam_id = fam.id
    acc = await make_account(session, fam_id)
    await _tx(session, a, fam_id, acc, 500, "solo")
    assert (await _delete(client, a)).status_code == 204
    session.expire_all()
    assert (
        await session.scalar(select(func.count()).select_from(Space).where(Space.id == fam_id)) == 0
    )
    assert await session.scalar(select(func.count()).select_from(Transaction)) == 0


async def test_export_hides_other_spaces_on_shared_account_and_secrets(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    fam = await make_family(session, a, b)
    shared = await make_account(session, fam.id, name="Conjunta")
    acc_b = await make_account(session, b.default_space_id, name="Pessoal do b")
    await _tx(session, b, b.default_space_id, shared, 4_000, "privado-do-b")  # conta compartilhada
    await _tx(session, b, fam.id, acc_b, 800, "familia-na-conta-do-b")
    a.totp_secret = "JBSWY3DPEHPK3PXP"
    await session.commit()
    ha = auth(a)
    await client.post("/auth/login", json={"email": "a@x.com", "password": PWD})  # cria refresh
    r = await client.get("/privacy/export", headers=ha)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    raw = z.read("data.json").decode() + z.read("transactions.csv").decode()
    assert "privado-do-b" not in raw and "Pessoal do b" not in raw and "b@x.com" not in raw
    data = json.loads(z.read("data.json"))
    (t,) = data["transactions"]
    assert t["description"] == "familia-na-conta-do-b" and t["account_id"] is None
    for secret in ("password_hash", "totp_secret", "JBSWY3DPEHPK3PXP", "token_hash"):
        assert secret not in raw
    assert "refresh_tokens" not in data


async def test_delete_requires_totp_when_enabled(client, session):
    import pyotp

    a = await make_user(session, "a@x.com")
    a.totp_secret, a.totp_enabled = pyotp.random_base32(), True
    await session.commit()
    secret, a_id = a.totp_secret, a.id
    r = await _delete(client, a)
    assert r.status_code == 401 and r.json() == {"detail": "totp_required"}
    r = await client.request(
        "DELETE", "/privacy/account", json={"password": PWD, "totp": "000000"}, headers=auth(a)
    )
    assert r.status_code == 401
    r = await client.request(
        "DELETE",
        "/privacy/account",
        json={"password": PWD, "totp": pyotp.TOTP(secret).now()},
        headers=auth(a),
    )
    assert r.status_code == 204
    session.expire_all()
    assert await session.scalar(select(func.count()).select_from(User).where(User.id == a_id)) == 0


async def test_delete_is_rate_limited(client, session):
    a = await make_user(session, "a@x.com")
    for _ in range(5):
        assert (await _delete(client, a, "senha errada aqui")).status_code == 401
    assert (await _delete(client, a, "senha errada aqui")).status_code == 429
    assert (await _delete(client, a)).status_code == 429  # nem a senha certa passa


async def test_delete_revokes_tokens_and_audits_without_secrets(client, session):
    from app.domain.audit import AuditLog
    from app.domain.users.models import RefreshToken

    a = await make_user(session, "a@x.com")
    a_id = a.id
    ha = auth(a)
    assert (
        await client.post("/auth/login", json={"email": "a@x.com", "password": PWD})
    ).status_code == 200
    assert await session.scalar(select(func.count()).select_from(RefreshToken)) == 1
    assert (await _delete(client, a)).status_code == 204
    session.expire_all()
    assert await session.scalar(select(func.count()).select_from(RefreshToken)) == 0
    assert (await client.get("/spaces", headers=ha)).status_code == 401
    log = (await session.scalars(select(AuditLog).where(AuditLog.actor_id == a_id))).all()
    assert [r.action for r in log] == ["privacy.delete_account"]
    assert log[0].data == {} and PWD not in str(log[0].data)
