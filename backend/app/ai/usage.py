import logging
from uuid import UUID

from app.ai.models import AiUsage
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
