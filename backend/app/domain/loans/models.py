from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Loan(Base):
    __tablename__ = "loans"
    __table_args__ = (
        CheckConstraint("kind IN ('financing', 'consortium')", name="ck_loans_kind"),
        CheckConstraint("installment_cents > 0", name="ck_loans_installment_positive"),
        CheckConstraint("installments_total BETWEEN 1 AND 480", name="ck_loans_total_range"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # financing | consortium
    name: Mapped[str] = mapped_column(String(100))
    installment_cents: Mapped[int] = mapped_column(BigInteger)
    installments_total: Mapped[int] = mapped_column(Integer)
    first_due_on: Mapped[date] = mapped_column(Date)
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("categories.id"))
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"))  # informativo
    notes: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
