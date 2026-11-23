from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import InboundMessage as Inbound
from app.domain.channels.models import InboundMessage


async def ingest(
    session: AsyncSession, msgs: Sequence[Inbound], enqueue: Callable[[UUID], Awaitable[None]]
) -> int:
    """Grava cada mensagem uma única vez (UNIQUE canal+id externo) e enfileira só as novas.

    Webhook e polling usam esta mesma porta de entrada. Devolve quantas eram novas."""
    new = 0
    for m in msgs:
        inbound_id = await session.scalar(
            insert(InboundMessage)
            .values(
                channel=m.channel, external_message_id=m.external_message_id,
                external_user_id=m.external_user_id, text=m.text, media_kind=m.media_kind,
                media_ref=m.media_ref, received_at=m.received_at,
            )
            .on_conflict_do_nothing(constraint="uq_inbound_channel_msgid")
            .returning(InboundMessage.id)
        )  # fmt: skip
        await session.commit()  # o worker precisa enxergar a linha
        if inbound_id is None:
            continue  # duplicata (reenvio ou entrega simultânea): nada a fazer
        try:
            await enqueue(inbound_id)
        except Exception:
            # sem fila a mensagem se perderia: remove a linha para o reenvio entrar de novo
            await session.execute(delete(InboundMessage).where(InboundMessage.id == inbound_id))
            await session.commit()
            raise
        new += 1
    return new
