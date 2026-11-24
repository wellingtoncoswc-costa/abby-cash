"""bill recurrence skips

Revision ID: b1c2d3e4f5a6
Revises: a9b8c7d6e5f4
Create Date: 2026-11-24 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | Sequence[str] | None = "a9b8c7d6e5f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bill_recurrence_skips",
        sa.Column("space_id", sa.UUID(), nullable=False),
        sa.Column("recurrence_id", sa.UUID(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"]),
        sa.PrimaryKeyConstraint("space_id", "recurrence_id", "due_on"),
    )


def downgrade() -> None:
    op.drop_table("bill_recurrence_skips")
