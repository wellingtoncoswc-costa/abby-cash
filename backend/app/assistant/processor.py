import logging
import re
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.registry import get_adapter
from app.core.db import SessionLocal
from app.domain.channels.linking import find_user_by_link, link_with_code
from app.domain.channels.models import InboundMessage
from app.domain.errors import DomainError

STALE = timedelta(minutes=5)
log = logging.getLogger(__name__)

UNLINKED = (
    "Oi! Eu sou a Abby Cash, assistente de finanças. Para usar este chat, abra o painel web, "
    "vá em Canais, escolha Vincular Telegram e envie aqui o código de 6 dígitos "
    "(ou toque no link que o painel mostra)."
)
INVALID_CODE = "Código inválido ou expirado. Gere um novo no painel web (Canais)."
TOO_MANY = "Muitas tentativas. Tente de novo em 1 hora."
ALREADY_LINKED = "Este Telegram já está vinculado a outra conta."
LINKED_OK = (
    "✅ Telegram vinculado, {name}! Agora é só me mandar seus gastos, "
    "por exemplo: gastei 45 no mercado."
)
FAILED = "Tive um problema ao processar sua mensagem. Tente de novo em instantes."

_CODE = re.compile(r"(?:/start(?:@\w+)?\s+)?([0-9]{6})", re.ASCII | re.IGNORECASE)


async def claim(session: AsyncSession, inbound_id: UUID) -> bool:
    """received -> processing de forma atômica: só um worker processa cada mensagem.
    Também retoma 'processing' parado há mais de 5 min (worker que caiu)."""
    got = await session.scalar(
        update(InboundMessage)
        .where(
            InboundMessage.id == inbound_id,
            or_(
                InboundMessage.status == "received",
                and_(
                    InboundMessage.status == "processing",
                    InboundMessage.updated_at < func.now() - STALE,
                ),
            ),
        )
        .values(status="processing", updated_at=func.now())
        .returning(InboundMessage.id)
    )
    await session.commit()
    return got is not None


async def unlinked(session: AsyncSession, channel: str, external_user_id: str, text: str) -> str:
    """Remetente desconhecido: só instrução fixa (ou vínculo, se mandou um código). Nada é gravado
    no domínio."""
    m = _CODE.fullmatch(text.strip())
    if not m:
        return UNLINKED
    try:
        user = await link_with_code(
            session, channel=channel, external_user_id=external_user_id, code=m.group(1)
        )
    except DomainError as e:
        return TOO_MANY if str(e) == "too_many_attempts" else ALREADY_LINKED
    if user is None:
        return INVALID_CODE
    return LINKED_OK.format(name=user.name.split()[0])


async def handle(session: AsyncSession, ctx: dict[str, Any], row: InboundMessage) -> str | None:
    user = await find_user_by_link(session, row.channel, row.external_user_id)
    if user is None:
        return await unlinked(session, row.channel, row.external_user_id, row.text or "")
    row.user_id = user.id
    return None  # ramo vinculado: a conversa entra no T3.4 (Step 8)


async def handle_inbound(ctx: dict[str, Any], inbound_id: UUID) -> None:
    async with SessionLocal() as session:
        if not await claim(session, inbound_id):
            return  # já processada (reentrega do ARQ, corrida)
        row = await session.get(InboundMessage, inbound_id)
        assert row is not None
        channel, external_user_id = row.channel, row.external_user_id  # escalares: rollback expira
        status = "processed"
        try:
            reply = await handle(session, ctx, row)
            await session.commit()
        except Exception:
            log.exception("process_inbound failed")
            await session.rollback()
            reply, status = FAILED, "failed"
        row = await session.get(InboundMessage, inbound_id, populate_existing=True)
        assert row is not None
        row.status = status
        await session.commit()
        if reply:
            try:
                await get_adapter(channel).send_text(external_user_id, reply)
            except Exception:
                log.exception("send_text failed")
