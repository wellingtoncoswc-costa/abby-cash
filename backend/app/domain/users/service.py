import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pyotp
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, hash_token, new_opaque_token, verify_password
from app.domain.users.models import RefreshToken, SignupInvite, User

REFRESH_DAYS = 30
# hash válido de senha aleatória: iguala o custo quando o e-mail não existe
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


class AuthError(Exception):
    pass


def _norm(email: str) -> str:
    return email.strip().lower()


async def create_admin(session: AsyncSession, *, email: str, name: str, password: str) -> User:
    user = User(email=_norm(email), name=name, password_hash=hash_password(password), is_admin=True)
    session.add(user)
    await session.commit()
    return user


async def create_signup_invite(
    session: AsyncSession, *, created_by: UUID, expires_at: datetime | None = None
) -> SignupInvite:
    inv = SignupInvite(
        code=secrets.token_urlsafe(8),
        created_by=created_by,
        expires_at=expires_at or datetime.now(UTC) + timedelta(days=7),
    )
    session.add(inv)
    await session.commit()
    return inv


async def register_user(
    session: AsyncSession, *, email: str, name: str, password: str, invite_code: str
) -> User:
    # FOR UPDATE serializa o consumo: duas requisições com o mesmo código não passam juntas
    inv = (
        await session.execute(
            select(SignupInvite).where(SignupInvite.code == invite_code).with_for_update()
        )
    ).scalar_one_or_none()
    email = _norm(email)
    taken = (await session.execute(select(User.id).where(User.email == email))).first()
    if inv is None or inv.used_by is not None or inv.expires_at <= datetime.now(UTC) or taken:
        await session.rollback()
        raise ValueError("invalid_invite")  # mesmo erro p/ e-mail já usado: não vaza existência
    user = User(email=email, name=name, password_hash=hash_password(password))
    session.add(user)
    await session.flush()
    inv.used_by, inv.used_at = user.id, datetime.now(UTC)
    await session.commit()
    return user


async def authenticate(session: AsyncSession, email: str, password: str, totp: str | None) -> User:
    user = (
        await session.execute(select(User).where(User.email == _norm(email)))
    ).scalar_one_or_none()
    ok = verify_password(password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not ok:
        raise AuthError("invalid_credentials")
    if user.totp_enabled:
        if not totp:
            raise AuthError("totp_required")
        assert user.totp_secret
        if not pyotp.TOTP(user.totp_secret).verify(totp, valid_window=1):
            raise AuthError("invalid_credentials")
    return user


async def issue_refresh(session: AsyncSession, user_id: UUID, family_id: UUID | None = None) -> str:
    raw, h = new_opaque_token()
    session.add(
        RefreshToken(
            user_id=user_id,
            family_id=family_id or uuid4(),
            token_hash=h,
            expires_at=datetime.now(UTC) + timedelta(days=REFRESH_DAYS),
        )
    )
    await session.commit()
    return raw


async def rotate_refresh(session: AsyncSession, raw: str) -> tuple[User, str]:
    tok = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)).with_for_update()
        )
    ).scalar_one_or_none()
    if tok is None:
        raise AuthError("invalid_refresh")
    now = datetime.now(UTC)
    if tok.revoked_at is not None:  # reuso: revoga a família inteira
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == tok.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await session.commit()
        raise AuthError("invalid_refresh")
    user = await session.get(User, tok.user_id)
    if tok.expires_at <= now or user is None:
        await session.rollback()
        raise AuthError("invalid_refresh")
    tok.revoked_at = now
    new = await issue_refresh(session, tok.user_id, tok.family_id)  # commita junto
    return user, new
