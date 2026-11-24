from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AiUsage(Base):
    """Consumo de IA por espaço (base para precificar na fase de venda)."""

    __tablename__ = "ai_usage"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # intent | receipt | stt
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    seconds: Mapped[float] = mapped_column(Float, default=0.0)  # áudio (não é dinheiro)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
