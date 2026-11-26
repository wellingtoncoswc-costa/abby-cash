"""investments

Revision ID: f7a8b9c0d1e2
Revises: d0e1f2a3b4c5
Create Date: 2026-11-25 14:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | Sequence[str] | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("spaces.id"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("ticker", sa.String(12)),
        sa.Column("rate_type", sa.String(8)),
        sa.Column("rate_bp", sa.Integer()),
        sa.Column("maturity_on", sa.Date()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('stock', 'fii', 'cdb', 'lci', 'lca')", name="ck_investments_kind"
        ),
        sa.CheckConstraint(
            "rate_type IS NULL OR rate_type IN ('cdi_pct', 'fixed')",
            name="ck_investments_rate_type",
        ),
        sa.CheckConstraint("rate_bp IS NULL OR rate_bp > 0", name="ck_investments_rate_bp"),
    )
    op.create_index("ix_investments_space_id", "investments", ["space_id"])
    op.create_table(
        "investment_movements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("investment_id", sa.Uuid(), sa.ForeignKey("investments.id"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6)),
        sa.Column("unit_price_cents", sa.BigInteger()),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('buy', 'redeem')", name="ck_investment_movements_kind"),
        sa.CheckConstraint("amount_cents > 0", name="ck_investment_movements_amount_positive"),
    )
    op.create_index(
        "ix_investment_movements_investment_id", "investment_movements", ["investment_id"]
    )
    op.create_table(
        "price_quotes",
        sa.Column("ticker", sa.String(12), primary_key=True),
        sa.Column("on_date", sa.Date(), primary_key=True),
        sa.Column("close_cents", sa.BigInteger(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("price_quotes")
    op.drop_table("investment_movements")
    op.drop_table("investments")
