"""transactions.goal_direction

Revision ID: b7d1c2a9e3f4
Revises: e54eefd5abb8
Create Date: 2026-11-23 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d1c2a9e3f4"
down_revision: str | Sequence[str] | None = "e54eefd5abb8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("goal_direction", sa.String(length=3), nullable=True))
    # aporte = sai de uma conta (account_id) sem contra-conta; o resto das linhas de meta é retirada
    op.execute(
        """UPDATE transactions SET goal_direction =
           CASE WHEN account_id IS NOT NULL AND counter_account_id IS NULL THEN 'in' ELSE 'out' END
           WHERE goal_id IS NOT NULL"""
    )
    op.create_check_constraint(
        "ck_transactions_goal_direction_valid", "transactions", "goal_direction IN ('in', 'out')"
    )
    op.create_check_constraint(
        "ck_transactions_goal_direction",
        "transactions",
        "(goal_id IS NULL) = (goal_direction IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_transactions_goal_direction", "transactions", type_="check")
    op.drop_constraint("ck_transactions_goal_direction_valid", "transactions", type_="check")
    op.drop_column("transactions", "goal_direction")
