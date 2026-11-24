import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiUsage
from app.core.config import get_settings
from app.core.db import SessionLocal

log = logging.getLogger(__name__)


async def record_ai_usage(
    space_id: UUID, kind: str, *, input_tokens: int = 0, output_tokens: int = 0,
    seconds: float = 0.0,
) -> None:  # fmt: skip
    """Sessão própria: o consumo é registrado mesmo se a conversa der rollback. Nunca derruba
    quem chamou."""
    try:
        async with SessionLocal() as session:
            session.add(
                AiUsage(
                    space_id=space_id, kind=kind, input_tokens=input_tokens,
                    output_tokens=output_tokens, seconds=seconds,
                )
            )  # fmt: skip
            await session.commit()
    except Exception:
        log.exception("record_ai_usage failed")


async def over_budget(session: AsyncSession, space_id: UUID, *, stt: bool = False) -> bool:
    """Consumo das últimas 24h do espaço acima do teto (tokens de IA, ou segundos de áudio)."""
    s = get_settings()
    col = AiUsage.seconds if stt else AiUsage.input_tokens + AiUsage.output_tokens
    used = await session.scalar(
        select(func.coalesce(func.sum(col), 0)).where(
            AiUsage.space_id == space_id,
            AiUsage.created_at > datetime.now(UTC) - timedelta(hours=24),
            AiUsage.kind == "stt" if stt else AiUsage.kind != "stt",
        )
    )
    return (used or 0) >= (s.STT_DAILY_SECONDS if stt else s.AI_DAILY_TOKEN_BUDGET)
