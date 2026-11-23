from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_transactions_amount_positive"),
        CheckConstraint(
            "goal_direction IN ('in', 'out')", name="ck_transactions_goal_direction_valid"
        ),
        CheckConstraint(
            "(goal_id IS NULL) = (goal_direction IS NULL)", name="ck_transactions_goal_direction"
        ),
        Index("ix_transactions_space_date", "space_id", "occurred_on"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"))
    type: Mapped[str] = mapped_column(String(16))  # expense | income | transfer
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    occurred_on: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(500), default="")
    merchant: Mapped[str | None] = mapped_column(String(200))
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("categories.id"))
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    counter_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    card_id: Mapped[UUID | None] = mapped_column(ForeignKey("credit_cards.id"), index=True)
    invoice_id: Mapped[UUID | None] = mapped_column(ForeignKey("invoices.id"), index=True)
    bill_id: Mapped[UUID | None] = mapped_column(ForeignKey("bills.id"), index=True)
    goal_id: Mapped[UUID | None] = mapped_column(ForeignKey("goals.id"), index=True)
    # in = aporte, out = retirada; explícito porque account_id vira NULL na exclusão de conta
    goal_direction: Mapped[str | None] = mapped_column(String(3))
    installment_group_id: Mapped[UUID | None] = mapped_column(index=True)
    installment_number: Mapped[int | None] = mapped_column(Integer)
    installment_total: Mapped[int | None] = mapped_column(Integer)
    # NULL = "Usuário removido"
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    origin: Mapped[str] = mapped_column(String(16), default="web")  # web | telegram | whatsapp_*
    source_message_id: Mapped[str | None] = mapped_column(String(128))
    attachment_id: Mapped[UUID | None] = mapped_column()  # tabela de anexos chega no M6
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
