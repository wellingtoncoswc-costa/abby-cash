import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.models import Account
from app.domain.audit import audit
from app.domain.categories.defaults import DEFAULT_EXPENSE, DEFAULT_INCOME
from app.domain.categories.models import Category
from app.domain.errors import DomainError
from app.domain.spaces.access import require_member
from app.domain.spaces.models import Space, SpaceInvite, SpaceMember
from app.domain.users.models import User

INVITE_DAYS = 7


def _seed_categories(session: AsyncSession, space_id: UUID) -> None:
    session.add_all(
        [Category(space_id=space_id, kind="expense", name=n) for n in DEFAULT_EXPENSE]
        + [Category(space_id=space_id, kind="income", name=n) for n in DEFAULT_INCOME]
    )


async def provision_user(session: AsyncSession, user: User) -> None:
    """Espaço pessoal + categorias + Carteira + membership. Só flush: quem chama commita."""
    space = Space(type="personal", name="Pessoal", owner_id=user.id)
    session.add(space)
    await session.flush()
    wallet = Account(space_id=space.id, type="wallet", name="Carteira")
    session.add(wallet)
    _seed_categories(session, space.id)
    await session.flush()
    audit(
        session, user.id, "account.create", "account", wallet.id,
        {"space_id": str(space.id), "type": "wallet"},
    )  # fmt: skip
    session.add(
        SpaceMember(space_id=space.id, user_id=user.id, role="owner", default_account_id=wallet.id)
    )
    user.default_space_id = space.id
    await session.flush()


async def create_family_space(session: AsyncSession, *, owner_id: UUID, name: str) -> Space:
    space = Space(type="family", name=name, owner_id=owner_id)
    session.add(space)
    try:
        # o índice único parcial é a garantia real (cobre corrida); sem checagem prévia
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise ValueError("family_space_exists") from None
    _seed_categories(session, space.id)
    session.add(SpaceMember(space_id=space.id, user_id=owner_id, role="owner"))
    audit(session, owner_id, "space.create_family", "space", space.id)
    await session.commit()
    return space


async def _require_owner(session: AsyncSession, user_id: UUID, space_id: UUID) -> None:
    if (await require_member(session, user_id, space_id)).role != "owner":
        raise HTTPException(status_code=403, detail="owner_only")


async def create_space_invite(
    session: AsyncSession, *, space_id: UUID, created_by: UUID
) -> SpaceInvite:
    await _require_owner(session, created_by, space_id)
    space = await session.get(Space, space_id)
    if space is None or space.type != "family":
        raise HTTPException(status_code=404, detail="not_found")
    inv = SpaceInvite(
        space_id=space_id,
        token=secrets.token_urlsafe(24),
        created_by=created_by,
        expires_at=datetime.now(UTC) + timedelta(days=INVITE_DAYS),
    )
    session.add(inv)
    await session.flush()
    audit(session, created_by, "space.invite", "space_invite", inv.id, {"space_id": str(space_id)})
    await session.commit()
    return inv


async def accept_space_invite(session: AsyncSession, *, token: str, user_id: UUID) -> UUID:
    # 1) trava o espaço (mesma ordem de delete_account: espaço, depois convite) para que a
    # exclusão do dono não purgue um membro novo; 2) UPDATE condicional atômico: um só consome
    sid = await session.scalar(select(SpaceInvite.space_id).where(SpaceInvite.token == token))
    locked = sid and await session.scalar(select(Space.id).where(Space.id == sid).with_for_update())
    space_id = (
        (
            await session.execute(
                update(SpaceInvite)
                .where(
                    SpaceInvite.token == token,
                    SpaceInvite.used_at.is_(None),
                    SpaceInvite.expires_at > datetime.now(UTC),
                )
                .values(used_at=datetime.now(UTC))
                .returning(SpaceInvite.space_id)
            )
        ).scalar_one_or_none()
        if locked
        else None
    )
    if space_id is None:
        await session.rollback()
        raise ValueError("invalid_invite")
    try:
        session.add(SpaceMember(space_id=space_id, user_id=user_id, role="member"))
        audit(session, user_id, "space.accept_invite", "space", space_id)
        await session.commit()
    except IntegrityError:  # já é membro: não consome o convite
        await session.rollback()
        raise ValueError("invalid_invite") from None
    return space_id


async def _drop_member(session: AsyncSession, space_id: UUID, user_id: UUID) -> int:
    res = await session.execute(
        delete(SpaceMember).where(SpaceMember.space_id == space_id, SpaceMember.user_id == user_id)
    )
    user = await session.get(User, user_id)
    if user is not None and user.default_space_id == space_id:
        user.default_space_id = await session.scalar(
            select(Space.id).where(Space.owner_id == user_id, Space.type == "personal")
        )
    return res.rowcount  # type: ignore[attr-defined,no-any-return]


async def remove_member(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, user_id: UUID
) -> None:
    await _require_owner(session, actor_id, space_id)
    space = await session.get(Space, space_id)
    if space is None or user_id == space.owner_id:
        raise ValueError("cannot_remove_owner")
    removed = await _drop_member(session, space_id, user_id)
    if removed:
        audit(
            session, actor_id, "space.remove_member", "space", space_id, {"user_id": str(user_id)}
        )
    await session.commit()
    if not removed:
        raise HTTPException(status_code=404, detail="not_found")


async def leave_space(session: AsyncSession, *, user_id: UUID, space_id: UUID) -> None:
    """O membro sai por conta própria. O dono não sai (apagar o espaço não existe na v1)."""
    member = await require_member(session, user_id, space_id)
    if member.role == "owner":
        raise DomainError("owner_cannot_leave")
    await _drop_member(session, space_id, user_id)
    audit(session, user_id, "space.leave", "space", space_id)
    await session.commit()


async def list_members(
    session: AsyncSession, *, viewer_id: UUID, space_id: UUID
) -> list[tuple[SpaceMember, str]]:
    """Só nome (nunca e-mail), papel e data de entrada."""
    await require_member(session, viewer_id, space_id)
    rows = await session.execute(
        select(SpaceMember, User.name)
        .join(User, User.id == SpaceMember.user_id)
        .where(SpaceMember.space_id == space_id)
        .order_by(SpaceMember.joined_at, User.name)
    )
    return [(m, n) for m, n in rows]
