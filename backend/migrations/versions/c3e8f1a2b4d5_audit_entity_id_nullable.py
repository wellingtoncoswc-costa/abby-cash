"""audit_log.entity_id nullable (LGPD scrub)

Revision ID: c3e8f1a2b4d5
Revises: b7d1c2a9e3f4
Create Date: 2026-11-23 15:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3e8f1a2b4d5"
down_revision: str | Sequence[str] | None = "b7d1c2a9e3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("audit_log", "entity_id", nullable=True)


def downgrade() -> None:
    op.execute("UPDATE audit_log SET entity_id = gen_random_uuid() WHERE entity_id IS NULL")
    op.alter_column("audit_log", "entity_id", nullable=False)
