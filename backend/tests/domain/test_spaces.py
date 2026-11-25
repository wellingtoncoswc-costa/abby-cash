from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.domain.accounts.models import Account
from app.domain.categories.models import Category
from app.domain.spaces.access import require_member
from app.domain.spaces.models import Space, SpaceMember
from app.domain.spaces.service import (
    accept_space_invite,
    create_family_space,
    create_space_invite,
    remove_member,
)
from app.domain.users.service import create_admin, create_signup_invite, register_user

PWD = "correct horse battery"


async def _user(session, email):
    admin = await create_admin(session, email=f"adm-{email}", name="Adm", password=PWD)
    inv = await create_signup_invite(session, created_by=admin.id)
    return await register_user(session, email=email, name=email, password=PWD, invite_code=inv.code)


async def test_signup_creates_personal_space_with_defaults_and_wallet(session):
    u = await _user(session, "a@x.com")
    assert u.default_space_id is not None
    space = await session.get(Space, u.default_space_id)
    assert space.type == "personal" and space.owner_id == u.id
    cats = (await session.scalars(select(Category).where(Category.space_id == space.id))).all()
    names = {c.name for c in cats if c.kind == "expense"}
    assert {"Alimentação", "Mercado", "Impostos e taxas", "Outros"} <= names
    assert {c.name for c in cats if c.kind == "income"} == {
        "Salário", "Renda extra", "Reembolso", "Outros"
    }  # fmt: skip
    wallet = await session.scalar(select(Account).where(Account.space_id == space.id))
    assert wallet.type == "wallet" and wallet.name == "Carteira"
    m = await require_member(session, u.id, space.id)
    assert m.role == "owner" and m.default_account_id == wallet.id


async def test_non_member_gets_404(session):
    a, b = await _user(session, "a@x.com"), await _user(session, "b@x.com")
    with pytest.raises(HTTPException) as e:
        await require_member(session, b.id, a.default_space_id)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException):
        await require_member(session, a.id, uuid4())


async def test_user_cannot_own_two_family_spaces(session):
    a = await _user(session, "a@x.com")
    await create_family_space(session, owner_id=a.id, name="Casa")
    with pytest.raises(ValueError, match="family_space_exists"):
        await create_family_space(session, owner_id=a.id, name="Outra")


async def test_removed_member_loses_access_immediately(session):
    a, b = await _user(session, "a@x.com"), await _user(session, "b@x.com")
    fam = await create_family_space(session, owner_id=a.id, name="Casa")
    inv = await create_space_invite(session, space_id=fam.id, created_by=a.id)
    await accept_space_invite(session, token=inv.token, user_id=b.id)
    assert (await require_member(session, b.id, fam.id)).role == "member"
    await remove_member(session, actor_id=a.id, space_id=fam.id, user_id=b.id)
    with pytest.raises(HTTPException):
        await require_member(session, b.id, fam.id)
    assert await session.get(SpaceMember, (fam.id, a.id)) is not None


async def test_invite_rules(session):
    a, b, c = [await _user(session, f"{n}@x.com") for n in "abc"]
    a, b, c = a.id, b.id, c.id  # rollback expira os objetos
    fam = await create_family_space(session, owner_id=a, name="Casa")
    fam_id = fam.id
    inv = await create_space_invite(session, space_id=fam_id, created_by=a)
    with pytest.raises(HTTPException):  # só owner convida
        await create_space_invite(session, space_id=fam_id, created_by=b)
    await accept_space_invite(session, token=inv.token, user_id=b)
    with pytest.raises(ValueError, match="invalid_invite"):  # uso único
        await accept_space_invite(session, token=inv.token, user_id=c)
    old = await create_space_invite(session, space_id=fam_id, created_by=a)
    old.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await session.commit()
    with pytest.raises(ValueError, match="invalid_invite"):  # expirado
        await accept_space_invite(session, token=old.token, user_id=c)
    with pytest.raises(HTTPException):  # só owner remove
        await remove_member(session, actor_id=b, space_id=fam_id, user_id=a)
    with pytest.raises(ValueError, match="cannot_remove_owner"):
        await remove_member(session, actor_id=a, space_id=fam_id, user_id=a)


async def test_family_space_has_default_categories_and_no_wallet(session):
    a = await _user(session, "a@x.com")
    fam = await create_family_space(session, owner_id=a.id, name="Casa")
    cats = (await session.scalars(select(Category).where(Category.space_id == fam.id))).all()
    assert {"Alimentação", "Mercado"} <= {c.name for c in cats if c.kind == "expense"}
    assert {c.name for c in cats if c.kind == "income"} == {
        "Salário", "Renda extra", "Reembolso", "Outros"
    }  # fmt: skip
    assert await session.scalar(select(Account).where(Account.space_id == fam.id)) is None


async def test_remove_member_resets_default_space_to_personal(session):
    a, b = await _user(session, "a@x.com"), await _user(session, "b@x.com")
    personal = b.default_space_id
    fam = await create_family_space(session, owner_id=a.id, name="Casa")
    inv = await create_space_invite(session, space_id=fam.id, created_by=a.id)
    await accept_space_invite(session, token=inv.token, user_id=b.id)
    b.default_space_id = fam.id
    await session.commit()
    await remove_member(session, actor_id=a.id, space_id=fam.id, user_id=b.id)
    await session.refresh(b)
    assert b.default_space_id == personal


async def test_create_admin_is_provisioned(session):
    adm = await create_admin(session, email="adm@x.com", name="Adm", password=PWD)
    assert adm.default_space_id is not None
    wallet = await session.scalar(select(Account).where(Account.space_id == adm.default_space_id))
    assert wallet is not None and wallet.type == "wallet"


async def test_leaving_clears_responsible_and_foreign_default_account(session):
    from datetime import date

    from app.domain.bills.service import create_bill
    from app.domain.spaces.service import leave_space
    from tests.factories import make_account

    a, b = await _user(session, "a@x.com"), await _user(session, "b@x.com")
    fam = await create_family_space(session, owner_id=a.id, name="Casa")
    inv = await create_space_invite(session, space_id=fam.id, created_by=a.id)
    await accept_space_invite(session, token=inv.token, user_id=b.id)
    bill = await create_bill(
        session, actor_id=a.id, space_id=fam.id, description="Luz", amount_cents=100,
        due_on=date(2026, 12, 1), responsible_user_id=b.id,
    )  # fmt: skip
    fam_acc = await make_account(session, fam.id)
    mine = await session.get(SpaceMember, (b.default_space_id, b.id))
    mine.default_account_id = fam_acc.id  # padrão pessoal apontando p/ conta da família
    await session.commit()
    await leave_space(session, user_id=b.id, space_id=fam.id)
    await session.refresh(bill)
    await session.refresh(mine)
    assert bill.responsible_user_id is None and mine.default_account_id is None
