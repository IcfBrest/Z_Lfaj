"""phase1: users.score_weights + background_tasks.params

Revision ID: 4b1f0c9d7a21
Revises: f5e498fb720c
Create Date: 2026-11-03
"""

import sqlalchemy as sa
from alembic import op

revision = "4b1f0c9d7a21"
down_revision = "f5e498fb720c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("score_weights", sa.JSON(), nullable=True))
    op.add_column("background_tasks", sa.Column("params", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("background_tasks", "params")
    op.drop_column("users", "score_weights")
