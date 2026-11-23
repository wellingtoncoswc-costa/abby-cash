"""inbound_messages.updated_at

Revision ID: d4a7b1c9e2f6
Revises: 134aabb324b8
Create Date: 2026-11-23 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4a7b1c9e2f6"
down_revision: str | Sequence[str] | None = "134aabb324b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "inbound_messages",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("inbound_messages", "updated_at")
