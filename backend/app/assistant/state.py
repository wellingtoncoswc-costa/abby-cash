from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.models import ConversationState

TTL = timedelta(minutes=30)


async def get_state(
    session: AsyncSession, user_id: UUID, channel: str, now: datetime
) -> ConversationState | None:
    """Pergunta pendente válida em `now` (hora da mensagem); expirada = como se não houvesse."""
    st = await session.get(ConversationState, (user_id, channel), populate_existing=True)
    if st is not None and st.expires_at <= now:
        await session.delete(st)
        await session.commit()
        return None
    return st


async def set_state(
    session: AsyncSession, user_id: UUID, channel: str, kind: str, data: dict[str, Any],
    now: datetime,
) -> None:  # fmt: skip
    st = await session.get(ConversationState, (user_id, channel), populate_existing=True)
    if st is None:
        st = ConversationState(user_id=user_id, channel=channel)
        session.add(st)
    st.kind, st.data, st.expires_at = kind, data, now + TTL
    await session.commit()


async def clear_state(session: AsyncSession, user_id: UUID, channel: str) -> None:
    await session.execute(
        delete(ConversationState).where(
            ConversationState.user_id == user_id, ConversationState.channel == channel
        )
    )
    await session.commit()
