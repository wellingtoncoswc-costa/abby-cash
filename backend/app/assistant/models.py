from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ConversationState(Base):
    """Pergunta pendente de um usuário num canal (uma por vez; expira em 30 min)."""

    __tablename__ = "conversation_state"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # amount|payment|confirm|pick_bill|correct|delete
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
