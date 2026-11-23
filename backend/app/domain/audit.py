from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_id: Mapped[UUID | None] = mapped_column(index=True)  # sem FK: sobrevive à exclusão
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[UUID] = mapped_column(index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # sem dados sensíveis
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def audit(
    session: AsyncSession, actor_id: UUID | None, action: str, entity: str, entity_id: UUID,
    data: dict[str, Any] | None = None,
) -> None:  # fmt: skip
    """Só adiciona à sessão: grava junto com o commit do serviço que chamou."""
    session.add(
        AuditLog(
            actor_id=actor_id, action=action, entity=entity, entity_id=entity_id, data=data or {}
        )
    )
