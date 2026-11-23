import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.registry import get_adapter
from app.domain.channels.models import ChannelLink
from app.domain.spaces.models import SpaceMember
from app.domain.users.models import User

log = logging.getLogger(__name__)


async def notify_members(
    session: AsyncSession, space_id: UUID, exclude_user_id: UUID, text: str
) -> None:
    """Avisa os OUTROS membros do espaço pelo canal preferido de cada um (ou o primeiro vinculado).
    O alerta de teto é do espaço: quem cruza o limiar não pode ser o único a saber.
    ponytail: sem fallback entre canais; o M4 troca por `notify_user`."""
    rows = (
        await session.execute(
            select(
                User.id, User.preferred_channel, ChannelLink.channel, ChannelLink.external_user_id
            )
            .join(SpaceMember, SpaceMember.user_id == User.id)
            .join(ChannelLink, ChannelLink.user_id == User.id)
            .where(SpaceMember.space_id == space_id, User.id != exclude_user_id)
            .order_by(User.id, ChannelLink.channel)
        )
    ).all()
    chosen: dict[UUID, tuple[str, str]] = {}
    for uid, preferred, channel, external in rows:
        if uid not in chosen or channel == preferred:
            chosen[uid] = (channel, external)
    for channel, external in chosen.values():
        try:
            await get_adapter(channel).send_text(external, text)
        except Exception as e:
            log.warning("notify_members failed (%s)", type(e).__name__)
