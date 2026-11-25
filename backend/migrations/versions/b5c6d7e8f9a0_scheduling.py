"""scheduling: bills.recurrence_id and bill_reminders_sent

Revision ID: b5c6d7e8f9a0
Revises: a3b4c5d6e7f8
Create Date: 2026-11-23 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5c6d7e8f9a0"
down_revision: str | Sequence[str] | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bills", sa.Column("recurrence_id", sa.Uuid(), nullable=True))
    op.execute("UPDATE bills SET recurrence_id = id WHERE recurrence_rule IS NOT NULL")
    op.create_unique_constraint(
        "uq_bills_recurrence_due", "bills", ["space_id", "recurrence_id", "due_on"]
    )
    op.create_table(
        "bill_reminders_sent",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bill_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["bill_id"], ["bills.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bill_id", "user_id", "kind", name="uq_bill_reminder_once"),
    )
    op.create_index("ix_bill_reminders_sent_bill_id", "bill_reminders_sent", ["bill_id"])
    op.create_index("ix_bill_reminders_sent_user_id", "bill_reminders_sent", ["user_id"])


def downgrade() -> None:
    op.drop_table("bill_reminders_sent")
    op.drop_constraint("uq_bills_recurrence_due", "bills", type_="unique")
    op.drop_column("bills", "recurrence_id")
