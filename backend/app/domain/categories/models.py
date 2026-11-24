from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # expense | income
    name: Mapped[str] = mapped_column(String(100))
    icon: Mapped[str | None] = mapped_column(String(32))
    color: Mapped[str | None] = mapped_column(String(16))
