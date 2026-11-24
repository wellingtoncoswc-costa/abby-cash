"""attachments

Revision ID: c7d8e9f0a1b2
Revises: b5c6d7e8f9a0
Create Date: 2026-11-24 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: str | Sequence[str] | None = "b5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(100), nullable=False),
        sa.Column("mime", sa.String(32), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("source_message_id", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("origin", "source_message_id", name="uq_attachments_origin_message"),
    )  # fmt: skip
    op.create_index("ix_attachments_space_id", "attachments", ["space_id"])
    op.create_foreign_key(
        "fk_transactions_attachment_id", "transactions", "attachments", ["attachment_id"], ["id"],
        ondelete="SET NULL",
    )  # fmt: skip


def downgrade() -> None:
    op.drop_constraint("fk_transactions_attachment_id", "transactions", type_="foreignkey")
    op.drop_index("ix_attachments_space_id", table_name="attachments")
    op.drop_table("attachments")
