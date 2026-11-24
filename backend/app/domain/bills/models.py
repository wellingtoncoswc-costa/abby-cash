from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Bill(Base):
    __tablename__ = "bills"
    __table_args__ = (
        CheckConstraint("amount_cents >= 0", name="ck_bills_amount_nonneg"),
        UniqueConstraint("space_id", "recurrence_id", "due_on", name="uq_bills_recurrence_due"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # manual | invoice
    description: Mapped[str] = mapped_column(String(200))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    due_on: Mapped[date] = mapped_column(Date, index=True)
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("categories.id"))
    responsible_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | paid | partial
    recurrence_rule: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    recurrence_id: Mapped[UUID | None] = mapped_column()  # id da conta-origem (que tem a regra)
    invoice_id: Mapped[UUID | None] = mapped_column(ForeignKey("invoices.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BillReminderSent(Base):
    __tablename__ = "bill_reminders_sent"
    __table_args__ = (UniqueConstraint("bill_id", "user_id", "kind", name="uq_bill_reminder_once"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    bill_id: Mapped[UUID] = mapped_column(ForeignKey("bills.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # day_before | due | overdue
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BillRecurrenceSkip(Base):
    """Ocorrência gerada que o usuário apagou: `_generate` não a recria."""

    __tablename__ = "bill_recurrence_skips"

    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), primary_key=True)
    recurrence_id: Mapped[UUID] = mapped_column(primary_key=True)
    due_on: Mapped[date] = mapped_column(Date, primary_key=True)
