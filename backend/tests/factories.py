from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.core.security import create_access_token
from app.domain.accounts.models import Account
from app.domain.cards.service import create_card
from app.domain.categories.models import Category
from app.domain.channels.models import ChannelLink, InboundMessage
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


async def make_card(
    session, actor: User, space_id: UUID, *, name: str = "Visa", closing_day: int = 10,
    due_day: int = 20, limit_cents: int | None = None, payment_account_id: UUID | None = None,
):  # fmt: skip
    return await create_card(
        session, actor_id=actor.id, space_id=space_id, name=name, closing_day=closing_day,
        due_day=due_day, limit_cents=limit_cents, payment_account_id=payment_account_id,
    )  # fmt: skip


TS = datetime(2026, 11, 25, 15, 0, tzinfo=UTC)  # quarta-feira, 12:00 em São Paulo


async def make_link(session, user: User, ext: str = "111", channel: str = "telegram") -> None:
    session.add(ChannelLink(user_id=user.id, channel=channel, external_user_id=ext))
    await session.commit()


async def make_inbound(
    session, text: str | None, *, ext: str = "111", msg_id: int = 1, channel: str = "telegram",
    ts: datetime = TS, media_kind: str | None = None,
) -> UUID:  # fmt: skip
    row = InboundMessage(
        channel=channel, external_message_id=f"{ext}:{msg_id}", external_user_id=ext, text=text,
        media_kind=media_kind, media_ref="file-1" if media_kind else None, received_at=ts,
    )  # fmt: skip
    session.add(row)
    await session.commit()
    return row.id
