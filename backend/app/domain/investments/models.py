from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Investment(Base):
    __tablename__ = "investments"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('stock', 'fii', 'cdb', 'lci', 'lca')", name="ck_investments_kind"
        ),
        CheckConstraint(
            "rate_type IS NULL OR rate_type IN ('cdi_pct', 'fixed')",
            name="ck_investments_rate_type",
        ),
        CheckConstraint("rate_bp IS NULL OR rate_bp > 0", name="ck_investments_rate_bp"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # stock | fii | cdb | lci | lca
    name: Mapped[str] = mapped_column(String(100))
    ticker: Mapped[str | None] = mapped_column(String(12))  # só stock/fii
    rate_type: Mapped[str | None] = mapped_column(String(8))  # cdi_pct | fixed (renda fixa)
    rate_bp: Mapped[int | None] = mapped_column(Integer)  # % x 100: 110% CDI = 11000
    maturity_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvestmentMovement(Base):
    __tablename__ = "investment_movements"
    __table_args__ = (
        CheckConstraint("kind IN ('buy', 'redeem')", name="ck_investment_movements_kind"),
        CheckConstraint("amount_cents > 0", name="ck_investment_movements_amount_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    investment_id: Mapped[UUID] = mapped_column(ForeignKey("investments.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    occurred_on: Mapped[date] = mapped_column(Date)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))  # só stock/fii
    unit_price_cents: Mapped[int | None] = mapped_column(BigInteger)  # preço da data, guardado
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"))
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PriceQuote(Base):
    """Fechamento diário de um ticker (base da evolução e das comparações)."""

    __tablename__ = "price_quotes"

    ticker: Mapped[str] = mapped_column(String(12), primary_key=True)
    on_date: Mapped[date] = mapped_column(Date, primary_key=True)
    close_cents: Mapped[int] = mapped_column(BigInteger)
