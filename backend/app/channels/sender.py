import logging
from uuid import UUID

from sqlalchemy import select

from app.channels.registry import get_adapter
from app.core.db import SessionLocal
from app.domain.channels.models import ChannelLink, OutboundMessage
from app.domain.users.models import User

log = logging.getLogger(__name__)


async def notify_user(user_id: UUID, text: str, *, prefer: str | None = None) -> str | None:
    """Envia ao usuário pelo canal preferido e, se falhar, pelos outros vinculados (um por vez).
    Cada tentativa vira uma linha em `outbound_messages` (sem o texto). Devolve o canal que
    entregou, ou None. Nunca levanta: alerta que falha não pode derrubar quem o dispara."""
    async with SessionLocal() as s:
        links = {
            c: e
            for c, e in (
                await s.execute(
                    select(ChannelLink.channel, ChannelLink.external_user_id)
                    .where(ChannelLink.user_id == user_id)
                    .order_by(ChannelLink.channel)
                )
            ).all()
        }
        user = await s.get(User, user_id)
        first = [c for c in (prefer, user and user.preferred_channel) if c in links]
        for channel in dict.fromkeys(first + list(links)):
            kind: str | None = None
            try:
                await get_adapter(channel).send_text(links[channel], text)
            except Exception as e:
                kind = type(e).__name__
                log.warning("notify_user via %s failed (%s)", channel, kind)
            s.add(
                OutboundMessage(
                    user_id=user_id,
                    channel=channel,
                    status="failed" if kind else "ok",
                    error_kind=kind,
                )  # fmt: skip
            )
            await s.commit()
            if kind is None:
                return channel
    return None
