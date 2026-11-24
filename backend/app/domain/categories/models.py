from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint
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


class CategoryRule(Base):
    """Aprendizado: estabelecimento normalizado -> categoria (precedência sobre o LLM)."""

    __tablename__ = "category_rules"
    __table_args__ = (
        UniqueConstraint("space_id", "merchant_norm", name="uq_category_rules_space_merchant"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    merchant_norm: Mapped[str] = mapped_column(String(200))
    category_id: Mapped[UUID] = mapped_column(ForeignKey("categories.id"))
