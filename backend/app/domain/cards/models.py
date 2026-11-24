from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CreditCard(Base):
    __tablename__ = "credit_cards"
    __table_args__ = (
        CheckConstraint(
            "closing_day BETWEEN 1 AND 31 AND due_day BETWEEN 1 AND 31", name="ck_credit_cards_days"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    closing_day: Mapped[int] = mapped_column(Integer)
    due_day: Mapped[int] = mapped_column(Integer)
    limit_cents: Mapped[int | None] = mapped_column(BigInteger)
    payment_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"))


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("card_id", "closing_on", name="uq_invoices_card_closing"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    card_id: Mapped[UUID] = mapped_column(ForeignKey("credit_cards.id"))
    closing_on: Mapped[date] = mapped_column(Date)
    due_on: Mapped[date] = mapped_column(Date, index=True)
