from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.models import ConversationState
from app.domain.attachments import discard_draft_attachment

TTL = timedelta(minutes=30)


async def get_state(
    session: AsyncSession, user_id: UUID, channel: str, now: datetime
) -> ConversationState | None:
    """Pergunta pendente válida em `now` (hora da mensagem); expirada = como se não houvesse."""
    st = await session.get(ConversationState, (user_id, channel), populate_existing=True)
    if st is not None and st.expires_at <= now:
        data = dict(st.data)
        await session.delete(st)
        await session.commit()
        await discard_draft_attachment(session, data)
        return None
    return st


async def set_state(
    session: AsyncSession, user_id: UUID, channel: str, kind: str, data: dict[str, Any],
    now: datetime,
) -> None:  # fmt: skip
    old = await session.get(ConversationState, (user_id, channel), populate_existing=True)
    prev = dict(old.data) if old is not None else {}
    values = {"kind": kind, "data": data, "expires_at": now + TTL}
    await session.execute(
        insert(ConversationState)
        .values(user_id=user_id, channel=channel, **values)
        .on_conflict_do_update(index_elements=["user_id", "channel"], set_=values)
    )
    await session.commit()
    if (prev.get("draft") or {}).get("attachment_id") != (data.get("draft") or {}).get(
        "attachment_id"
    ):  # rascunho trocado por outro: a imagem do antigo não serve mais
        await discard_draft_attachment(session, prev)


async def clear_state(session: AsyncSession, user_id: UUID, channel: str) -> bool:
    """Apaga a pergunta pendente; True só para quem de fato a apagou (consumo atômico: de duas
    respostas simultâneas, só uma segue adiante)."""
    gone = await session.scalar(
        delete(ConversationState)
        .where(ConversationState.user_id == user_id, ConversationState.channel == channel)
        .returning(ConversationState.user_id)
    )
    await session.commit()
    return gone is not None
