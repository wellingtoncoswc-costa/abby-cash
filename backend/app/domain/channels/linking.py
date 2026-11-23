import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis
from app.domain.audit import audit
from app.domain.channels.models import ChannelLink
from app.domain.errors import DomainError
from app.domain.users.models import User

CODE_TTL_S = 600  # 10 minutos
MAX_FAILS = (
    10  # falhas por remetente por hora (vale entre códigos: limita força bruta de 6 dígitos)
)
FAIL_TTL_S = 3600
MAX_TRIES_PER_CODE = 5  # apresentações de um código existente (ex.: no canal errado)


def _key(code: str) -> str:
    return f"linkcode:{code}"


async def create_link_code(user_id: UUID, channel: str) -> str:
    """Código de 6 dígitos, válido por 10 min, de uso único (vive no Redis)."""
    for _ in range(10):  # colisão entre códigos ativos é improvável; tenta de novo
        code = f"{secrets.randbelow(10**6):06d}"
        if await redis.set(_key(code), f"{user_id}:{channel}", ex=CODE_TTL_S, nx=True):
            return code
    raise DomainError("code_generation_failed")


async def link_with_code(
    session: AsyncSession, *, channel: str, external_user_id: str, code: str
) -> User | None:
    """Vincula o remetente ao dono do código. None = código inválido/expirado/de outro canal."""
    fails = f"link_fails:{channel}:{external_user_id}"
    await redis.set(fails, 0, ex=FAIL_TTL_S, nx=True)  # TTL garantido antes do INCR
    if await redis.incr(fails) > MAX_FAILS:  # incr primeiro: atômico; conta toda tentativa
        raise DomainError("too_many_attempts")
    value = await redis.get(_key(code))
    if value is None:
        return None
    uid, _, code_channel = str(value).partition(":")
    if code_channel != channel:
        tries = f"linktries:{code}"
        await redis.set(tries, 0, ex=CODE_TTL_S, nx=True)
        if await redis.incr(tries) >= MAX_TRIES_PER_CODE:
            await redis.delete(_key(code), tries)
        return None
    if await redis.delete(_key(code)) == 0:  # outro processo consumiu primeiro
        return None
    user = await session.get(User, UUID(uid))
    if user is None:
        return None
    taken = await session.scalar(
        select(ChannelLink).where(
            ChannelLink.channel == channel, ChannelLink.external_user_id == external_user_id
        )
    )
    if taken is not None and taken.user_id != user.id:
        raise DomainError("already_linked")
    mine = await session.scalar(
        select(ChannelLink).where(ChannelLink.user_id == user.id, ChannelLink.channel == channel)
    )
    if mine is None:
        session.add(
            ChannelLink(user_id=user.id, channel=channel, external_user_id=external_user_id)
        )
    else:  # trocou de conta no canal
        mine.external_user_id = external_user_id
        mine.verified_at = datetime.now(UTC)
    if user.preferred_channel is None:
        user.preferred_channel = channel
    audit(session, user.id, "channel.link", "user", user.id, {"channel": channel})
    await session.commit()
    await redis.delete(fails)  # sucesso não conta como falha
    return user


async def find_user_by_link(
    session: AsyncSession, channel: str, external_user_id: str
) -> User | None:
    return await session.scalar(
        select(User)
        .join(ChannelLink, ChannelLink.user_id == User.id)
        .where(ChannelLink.channel == channel, ChannelLink.external_user_id == external_user_id)
    )


async def unlink(session: AsyncSession, user_id: UUID, channel: str) -> None:
    await session.execute(
        delete(ChannelLink).where(ChannelLink.user_id == user_id, ChannelLink.channel == channel)
    )
    audit(session, user_id, "channel.unlink", "user", user_id, {"channel": channel})
    await session.commit()
