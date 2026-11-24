import logging
from typing import Any

from sqlalchemy import select

from app.channels.registry import evolution_adapter
from app.channels.sender import notify_user
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.redis import redis
from app.domain.users.models import User

log = logging.getLogger(__name__)
DOWN_KEY = "evolution:down"
DOWN = "⚠️ O WhatsApp da Abby está desconectado (estado: {state}). Leia o QR code na Evolution."


async def check_evolution_connection(ctx: dict[str, Any] | None = None) -> None:
    """Cron de 5 min. Instância fora do ar -> avisa os admins pelo Telegram UMA vez por incidente
    (a chave no Redis vive até a instância voltar a `open`)."""
    if not get_settings().EVOLUTION_URL:
        return
    try:
        state = await evolution_adapter().client.connection_state()
    except Exception as e:
        state = f"inacessível ({type(e).__name__})"
    if state == "open":
        await redis.delete(DOWN_KEY)
        return
    if not await redis.set(DOWN_KEY, state, nx=True):
        return  # incidente já avisado
    async with SessionLocal() as s:
        admins = list(await s.scalars(select(User.id).where(User.is_admin)))
    for uid in admins:
        await notify_user(uid, DOWN.format(state=state), prefer="telegram")
    log.warning("evolution disconnected (%s)", state)
