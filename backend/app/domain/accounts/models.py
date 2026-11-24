from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))  # checking | wallet | savings
    name: Mapped[str] = mapped_column(String(100))
    initial_balance_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    institution: Mapped[str | None] = mapped_column(String(40))  # chave do catálogo do web
