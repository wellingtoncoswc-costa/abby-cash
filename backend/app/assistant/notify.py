import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.sender import notify_user
from app.domain.spaces.models import SpaceMember

SEND_TIMEOUT_S = 8


async def notify_members(
    session: AsyncSession, space_id: UUID, exclude_user_id: UUID, text: str
) -> None:
    """Avisa os OUTROS membros do espaço pelo canal preferido de cada um (ou o primeiro vinculado).
    O alerta de teto é do espaço: quem cruza o limiar não pode ser o único a saber.
    Usa `notify_user` (fallback entre canais)."""
    ids = await session.scalars(
        select(SpaceMember.user_id).where(
            SpaceMember.space_id == space_id, SpaceMember.user_id != exclude_user_id
        )
    )
    # em paralelo e com teto de tempo: canal lento não atrasa a resposta de quem lançou
    await asyncio.gather(
        *(asyncio.wait_for(notify_user(uid, text), SEND_TIMEOUT_S) for uid in list(ids)),
        return_exceptions=True,  # inclui TimeoutError; notify_user nunca levanta
    )
