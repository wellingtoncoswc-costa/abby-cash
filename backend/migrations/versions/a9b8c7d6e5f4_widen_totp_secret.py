"""widen totp_secret for encryption at rest

Revision ID: a9b8c7d6e5f4
Revises: d8e9f0a1b2c3
Create Date: 2026-11-24 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9b8c7d6e5f4"
down_revision: str | Sequence[str] | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "totp_secret", existing_type=sa.String(64), type_=sa.String(255))


def downgrade() -> None:
    op.alter_column("users", "totp_secret", existing_type=sa.String(255), type_=sa.String(64))
