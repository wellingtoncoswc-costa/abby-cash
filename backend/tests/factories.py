from uuid import UUID

from sqlalchemy import select

from app.core.security import create_access_token
from app.domain.accounts.models import Account
from app.domain.categories.models import Category
from app.domain.spaces.models import Space
from app.domain.spaces.service import (
    accept_space_invite,
    create_family_space,
    create_space_invite,
)
from app.domain.users.models import User
from app.domain.users.service import create_admin, create_signup_invite, register_user

PWD = "correct horse battery"


async def make_user(session, email: str) -> User:
    admin = await create_admin(session, email=f"adm-{email}", name="Adm", password=PWD)
    inv = await create_signup_invite(session, created_by=admin.id)
    return await register_user(session, email=email, name=email, password=PWD, invite_code=inv.code)


async def make_family(session, owner: User, *members: User) -> Space:
    fam = await create_family_space(session, owner_id=owner.id, name="Casa")
    for m in members:
        inv = await create_space_invite(session, space_id=fam.id, created_by=owner.id)
        await accept_space_invite(session, token=inv.token, user_id=m.id)
    return fam


async def make_account(
    session, space_id: UUID, *, name: str = "Conta", type: str = "checking", initial: int = 0
) -> Account:
    acc = Account(space_id=space_id, type=type, name=name, initial_balance_cents=initial)
    session.add(acc)
    await session.commit()
    return acc


async def category_id(
    session, space_id: UUID, name: str = "Mercado", kind: str = "expense"
) -> UUID:
    cid = await session.scalar(
        select(Category.id).where(
            Category.space_id == space_id, Category.name == name, Category.kind == kind
        )
    )
    assert cid is not None
    return cid


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}
