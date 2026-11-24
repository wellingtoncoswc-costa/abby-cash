from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Pocket(Base):
    __tablename__ = "pockets"
    __table_args__ = (CheckConstraint("cdi_bp BETWEEN 1 AND 100000", name="ck_pockets_cdi_bp"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    cdi_bp: Mapped[int] = mapped_column(Integer)  # % do CDI x 100 (120,00% = 12000)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PocketMovement(Base):
    __tablename__ = "pocket_movements"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_pocket_movements_amount_positive"),
        CheckConstraint(
            "kind IN ('deposit', 'withdraw', 'accrual')", name="ck_pocket_movements_kind"
        ),
        Index(
            "uq_pocket_movements_accrual",
            "pocket_id",
            "ref_date",
            unique=True,
            postgresql_where=text("kind = 'accrual'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    pocket_id: Mapped[UUID] = mapped_column(ForeignKey("pockets.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # deposit | withdraw | accrual
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    occurred_on: Mapped[date] = mapped_column(Date)
    ref_date: Mapped[date | None] = mapped_column(Date)  # accrual: dia do CDI
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CdiRate(Base):
    __tablename__ = "cdi_rates"

    on_date: Mapped[date] = mapped_column(Date, primary_key=True)
    daily_pct: Mapped[Decimal] = mapped_column(Numeric(14, 10))  # % ao dia


class PocketYieldPosting(Base):
    """Receita mensal "Rendimento" já lançada (idempotência: uma por caixinha e mês)."""

    __tablename__ = "pocket_yield_postings"

    pocket_id: Mapped[UUID] = mapped_column(ForeignKey("pockets.id"), primary_key=True)
    month: Mapped[str] = mapped_column(String(7), primary_key=True)  # YYYY-MM
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id"))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
