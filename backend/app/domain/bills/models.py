from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Bill(Base):
    __tablename__ = "bills"
    __table_args__ = (CheckConstraint("amount_cents >= 0", name="ck_bills_amount_nonneg"),)

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
    invoice_id: Mapped[UUID | None] = mapped_column(ForeignKey("invoices.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
