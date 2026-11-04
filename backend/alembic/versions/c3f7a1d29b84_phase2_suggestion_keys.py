"""phase2: suggestions 增加 match_result_id / resume_version 与唯一键

Revision ID: c3f7a1d29b84
Revises: 4b1f0c9d7a21
Create Date: 2026-11-04
"""

import sqlalchemy as sa
from alembic import op

revision = "c3f7a1d29b84"
down_revision = "4b1f0c9d7a21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("suggestions") as batch:
        batch.add_column(sa.Column("match_result_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("resume_version", sa.Integer(), nullable=False, server_default="1"))
        batch.create_index("ix_suggestions_match_result_id", ["match_result_id"])
        batch.create_foreign_key(
            "fk_suggestions_match_result_id", "match_results", ["match_result_id"], ["id"]
        )
        batch.create_unique_constraint(
            "uq_suggestions_user_match_version",
            ["user_id", "match_result_id", "resume_version"],
        )


def downgrade() -> None:
    with op.batch_alter_table("suggestions") as batch:
        batch.drop_constraint("uq_suggestions_user_match_version", type_="unique")
        batch.drop_constraint("fk_suggestions_match_result_id", type_="foreignkey")
        batch.drop_index("ix_suggestions_match_result_id")
        batch.drop_column("resume_version")
        batch.drop_column("match_result_id")
