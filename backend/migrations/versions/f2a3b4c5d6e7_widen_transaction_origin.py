"""widen transaction origin

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-23 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "transactions", "origin", existing_type=sa.String(16), type_=sa.String(32),
        existing_nullable=False,
    )  # fmt: skip


def downgrade() -> None:
    op.alter_column(
        "transactions", "origin", existing_type=sa.String(32), type_=sa.String(16),
        existing_nullable=False,
    )  # fmt: skip
