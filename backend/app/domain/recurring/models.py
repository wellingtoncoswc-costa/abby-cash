from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RecurringItem(Base):
    """Despesa/receita fixa. `account_id`: de onde sai (despesa) ou onde entra (receita)."""

    __tablename__ = "recurring_items"
    __table_args__ = (
        CheckConstraint("type IN ('expense', 'income')", name="ck_recurring_items_type"),
        CheckConstraint("amount_cents > 0", name="ck_recurring_items_amount_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    type: Mapped[str] = mapped_column(String(8))
    description: Mapped[str] = mapped_column(String(200))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("categories.id"))
    rule: Mapped[dict[str, Any]] = mapped_column(JSONB)  # bills.recurrence.Recurrence
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RecurringPosting(Base):
    """Data já lançada de um fixo (idempotência, mesmo se o lançamento for apagado depois)."""

    __tablename__ = "recurring_postings"

    item_id: Mapped[UUID] = mapped_column(
        ForeignKey("recurring_items.id", ondelete="CASCADE"), primary_key=True
    )
    due_on: Mapped[date] = mapped_column(Date, primary_key=True)
    transaction_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL")
    )
