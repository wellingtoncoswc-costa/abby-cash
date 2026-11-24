import os
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.core.db import Base

MAX_BYTES = 10 * 1024 * 1024


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        # idempotência: a mesma mensagem recebida nunca gera dois anexos
        UniqueConstraint("origin", "source_message_id", name="uq_attachments_origin_message"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    path: Mapped[str] = mapped_column(String(100))  # relativo a STORAGE_DIR: <space_id>/<uuid>
    mime: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    origin: Mapped[str] = mapped_column(String(32))
    source_message_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def sniff_image(data: bytes) -> str | None:
    """Tipo pelo conteúdo (magic bytes); extensão e mime enviados não valem nada."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def find_attachment(session: AsyncSession, origin: str, message_id: str) -> Attachment | None:
    return await session.scalar(
        select(Attachment).where(
            Attachment.origin == origin, Attachment.source_message_id == message_id
        )
    )


async def save_image(
    session: AsyncSession, *, space_id: UUID, origin: str, source_message_id: str, data: bytes
) -> Attachment | None:
    """Grava a imagem em STORAGE_DIR/<space_id>/<uuid> (nome aleatório, sem extensão; pasta 0700,
    arquivo 0600) e a linha. None se não for jpeg/png/webp ou passar de 10 MB."""
    mime = sniff_image(data)
    if mime is None or len(data) > MAX_BYTES:
        return None
    rel = f"{space_id}/{uuid4()}"
    full = Path(get_settings().STORAGE_DIR) / rel
    full.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(full, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    att = Attachment(
        space_id=space_id, path=rel, mime=mime, size_bytes=len(data), origin=origin,
        source_message_id=source_message_id,
    )  # fmt: skip
    session.add(att)
    await session.commit()
    return att


def remove_files(paths: list[str]) -> None:
    root = Path(get_settings().STORAGE_DIR)
    for p in paths:
        (root / p).unlink(missing_ok=True)


def read_file(att: Attachment) -> bytes:
    return (Path(get_settings().STORAGE_DIR) / att.path).read_bytes()
