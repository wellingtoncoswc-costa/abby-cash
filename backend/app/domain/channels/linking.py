import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import incr_ttl, redis
from app.domain.audit import audit
from app.domain.channels.models import ChannelLink
from app.domain.errors import DomainError
from app.domain.users.models import User

CODE_TTL_S = 600  # 10 minutos
MAX_FAILS = (
    10  # falhas por remetente por hora (vale entre códigos: limita força bruta de 6 dígitos)
)
FAIL_TTL_S = 3600
# teto global entre TODOS os remetentes: sem ele, rodar contas de Telegram contorna o limite
# por remetente e força bruta os 10^6 códigos. Conta toda apresentação (incl. sucesso).
# ponytail: 30 vínculos legítimos em 10 min travam todos; aceitável p/ app pessoal.
MAX_GLOBAL = 30
GLOBAL_TTL_S = 600


def _key(code: str) -> str:
    return f"linkcode:{code}"


def _user_key(user_id: UUID, channel: str) -> str:
    return f"linkuser:{user_id}:{channel}"


async def create_link_code(user_id: UUID, channel: str) -> str:
    """Código de 6 dígitos, válido por 10 min, de uso único (vive no Redis).
    Só um código vivo por usuário+canal: gerar outro invalida o anterior."""
    for _ in range(10):  # colisão entre códigos ativos é improvável; tenta de novo
        code = f"{secrets.randbelow(10**6):06d}"
        if await redis.set(_key(code), f"{user_id}:{channel}", ex=CODE_TTL_S, nx=True):
            old = await redis.set(_user_key(user_id, channel), code, ex=CODE_TTL_S, get=True)
            if old:
                await redis.delete(_key(str(old)))
            return code
    raise DomainError("code_generation_failed")


async def link_with_code(
    session: AsyncSession, *, channel: str, external_user_id: str, code: str
) -> User | None:
    """Vincula o remetente ao dono do código. None = código inválido/expirado/de outro canal
    (todos indistinguíveis); código de outro canal não é consumido."""
    fails = f"link_fails:{channel}:{external_user_id}"
    if await incr_ttl(fails, FAIL_TTL_S) > MAX_FAILS:  # incr primeiro: conta toda tentativa
        raise DomainError("too_many_attempts")
    if await incr_ttl("link_fails:global", GLOBAL_TTL_S) > MAX_GLOBAL:
        return None  # nem consulta nem consome o código
    value = await redis.get(_key(code))
    if value is None:
        return None
    uid, _, code_channel = str(value).partition(":")
    if code_channel != channel:
        return None
    if await redis.delete(_key(code)) == 0:  # outro processo consumiu primeiro
        return None
    await redis.delete(_user_key(UUID(uid), channel))
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
    try:
        await session.commit()
    except IntegrityError:  # corrida: o mesmo chat foi vinculado por outro código agora
        await session.rollback()
        raise DomainError("already_linked") from None
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
    user = await session.get(User, user_id)
    if user is not None and user.preferred_channel == channel:
        user.preferred_channel = await session.scalar(
            select(ChannelLink.channel).where(ChannelLink.user_id == user_id).limit(1)
        )
    audit(session, user_id, "channel.unlink", "user", user_id, {"channel": channel})
    await session.commit()
