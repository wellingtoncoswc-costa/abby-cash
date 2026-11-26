"""recurring items

Revision ID: a9b0c1d2e3f4
Revises: f7a8b9c0d1e2
Create Date: 2026-11-25 23:55:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a9b0c1d2e3f4"
down_revision: str | Sequence[str] | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recurring_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("spaces.id"), nullable=False),
        sa.Column("type", sa.String(8), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("categories.id")),
        sa.Column("rule", postgresql.JSONB(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date()),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("type IN ('expense', 'income')", name="ck_recurring_items_type"),
        sa.CheckConstraint("amount_cents > 0", name="ck_recurring_items_amount_positive"),
    )
    op.create_index("ix_recurring_items_space_id", "recurring_items", ["space_id"])
    op.create_index("ix_recurring_items_account_id", "recurring_items", ["account_id"])
    op.create_table(
        "recurring_postings",
        sa.Column(
            "item_id",
            sa.Uuid(),
            sa.ForeignKey("recurring_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("due_on", sa.Date(), primary_key=True),
        sa.Column(
            "transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id", ondelete="SET NULL")
        ),
    )


def downgrade() -> None:
    op.drop_table("recurring_postings")
    op.drop_table("recurring_items")
