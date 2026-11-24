from collections.abc import Awaitable, Callable, Sequence
from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, func, select
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
            # duplicata. Se ainda está 'received', um processo anterior pode ter morrido entre
            # o commit e o enqueue: reenfileira (o _job_id do ARQ dedupe); senão, nada a fazer
            stuck = await session.scalar(
                select(InboundMessage.id).where(
                    InboundMessage.channel == m.channel,
                    InboundMessage.external_message_id == m.external_message_id,
                    InboundMessage.status == "received",
                )
            )
            if stuck is not None:
                await enqueue(stuck)
            continue
        try:
            await enqueue(inbound_id)
        except Exception:
            # sem fila a mensagem se perderia: remove a linha para o reenvio entrar de novo
            await session.execute(delete(InboundMessage).where(InboundMessage.id == inbound_id))
            await session.commit()
            raise
        new += 1
    return new


async def purge_old_inbound(session: AsyncSession, days: int = 30) -> int:
    """Retenção: apaga as linhas de `inbound_messages` com mais de `days` dias. Devolve quantas.
    ponytail: sem job agendado ainda; por ora `python -m app.cli purge-inbound` (cron)."""
    res = await session.execute(
        delete(InboundMessage).where(InboundMessage.created_at < func.now() - timedelta(days=days))
    )
    await session.commit()
    return int(res.rowcount)  # type: ignore[attr-defined]
