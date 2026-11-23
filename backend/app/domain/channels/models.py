from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class InboundMessage(Base):
    __tablename__ = "inbound_messages"
    __table_args__ = (
        # idempotência: o mesmo webhook reenviado nunca vira duas linhas
        UniqueConstraint("channel", "external_message_id", name="uq_inbound_channel_msgid"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    channel: Mapped[str] = mapped_column(String(32))
    external_message_id: Mapped[str] = mapped_column(String(128))
    external_user_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    text: Mapped[str | None] = mapped_column(Text)
    media_kind: Mapped[str | None] = mapped_column(String(8))
    media_ref: Mapped[str | None] = mapped_column(String(512))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # received -> processing -> processed | failed
    status: Mapped[str] = mapped_column(String(16), default="received")
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChannelLink(Base):
    __tablename__ = "channel_links"
    __table_args__ = (
        UniqueConstraint("channel", "external_user_id", name="uq_channel_links_external"),
        UniqueConstraint("user_id", "channel", name="uq_channel_links_user_channel"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(String(32))
    external_user_id: Mapped[str] = mapped_column(String(64))  # chat_id / telefone
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
