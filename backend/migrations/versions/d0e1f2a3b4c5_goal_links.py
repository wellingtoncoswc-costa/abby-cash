"""goal links to accounts and pockets

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-11-25 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | Sequence[str] | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "goal_accounts",
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "goal_id", sa.Uuid(), sa.ForeignKey("goals.id", ondelete="CASCADE"), nullable=False
        ),
    )
    op.create_index("ix_goal_accounts_goal_id", "goal_accounts", ["goal_id"])
    op.create_table(
        "goal_pockets",
        sa.Column(
            "pocket_id",
            sa.Uuid(),
            sa.ForeignKey("pockets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "goal_id", sa.Uuid(), sa.ForeignKey("goals.id", ondelete="CASCADE"), nullable=False
        ),
    )
    op.create_index("ix_goal_pockets_goal_id", "goal_pockets", ["goal_id"])
    # o campo antigo era informativo e podia repetir: a meta mais antiga fica com a conta
    op.execute(
        "INSERT INTO goal_accounts (account_id, goal_id) "
        "SELECT DISTINCT ON (account_id) account_id, id FROM goals "
        "WHERE account_id IS NOT NULL ORDER BY account_id, created_at"
    )
    op.drop_column("goals", "account_id")


def downgrade() -> None:
    op.add_column("goals", sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id")))
    op.execute(
        "UPDATE goals g SET account_id = (SELECT min(a.account_id::text)::uuid "
        "FROM goal_accounts a WHERE a.goal_id = g.id)"
    )
    op.drop_table("goal_pockets")
    op.drop_table("goal_accounts")
