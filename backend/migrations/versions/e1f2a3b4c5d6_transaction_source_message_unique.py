"""transaction source message unique

Revision ID: e1f2a3b4c5d6
Revises: 462623d3af84
Create Date: 2026-11-23 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "462623d3af84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_transactions_origin_source_message",
        "transactions",
        ["origin", "source_message_id", sa.text("coalesce(installment_number, 0)")],
        unique=True,
        postgresql_where=sa.text("source_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_transactions_origin_source_message",
        table_name="transactions",
        postgresql_where=sa.text("source_message_id IS NOT NULL"),
    )
