"""pocket movement source message

Revision ID: a7b8c9d0e1f2
Revises: d1e2f3a4b5c6
Create Date: 2026-11-24 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pocket_movements",
        sa.Column("origin", sa.String(32), server_default="web", nullable=False),
    )
    op.add_column("pocket_movements", sa.Column("source_message_id", sa.String(128)))
    op.create_index(
        "uq_pocket_movements_origin_source_message",
        "pocket_movements",
        ["origin", "source_message_id"],
        unique=True,
        postgresql_where=sa.text("source_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_pocket_movements_origin_source_message",
        table_name="pocket_movements",
        postgresql_where=sa.text("source_message_id IS NOT NULL"),
    )
    op.drop_column("pocket_movements", "source_message_id")
    op.drop_column("pocket_movements", "origin")
