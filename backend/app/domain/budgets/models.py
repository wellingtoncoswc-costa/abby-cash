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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("space_id", "month", name="uq_budgets_space_month"),
        CheckConstraint("limit_cents > 0", name="ck_budgets_limit_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"))
    month: Mapped[date] = mapped_column(Date)  # sempre o dia 1
    limit_cents: Mapped[int] = mapped_column(BigInteger)


class BudgetCategory(Base):
    __tablename__ = "budget_categories"
    __table_args__ = (CheckConstraint("limit_cents > 0", name="ck_budget_categories_positive"),)

    budget_id: Mapped[UUID] = mapped_column(ForeignKey("budgets.id"), primary_key=True)
    category_id: Mapped[UUID] = mapped_column(ForeignKey("categories.id"), primary_key=True)
    limit_cents: Mapped[int] = mapped_column(BigInteger)


class BudgetAlertSent(Base):
    __tablename__ = "budget_alerts_sent"
    __table_args__ = (
        UniqueConstraint(
            "space_id", "month", "scope_key", "threshold", name="uq_budget_alert_once"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"))
    month: Mapped[date] = mapped_column(Date)
    scope_key: Mapped[str] = mapped_column(String(40))  # "general" ou o id da categoria
    threshold: Mapped[int] = mapped_column(Integer)  # 80 | 100 | 101 (101 = acima do teto)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
