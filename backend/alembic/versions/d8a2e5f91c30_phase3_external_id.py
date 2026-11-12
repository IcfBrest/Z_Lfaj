"""phase3: job_postings 增加 external_id 与采集去重唯一索引

Revision ID: d8a2e5f91c30
Revises: c3f7a1d29b84
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op

revision = "d8a2e5f91c30"
down_revision = "c3f7a1d29b84"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("job_postings") as batch:
        batch.add_column(sa.Column("external_id", sa.String(length=128), nullable=True))
        batch.create_index(
            "uq_job_postings_source_external",
            ["company_id", "source_type", "external_id"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("job_postings") as batch:
        batch.drop_index("uq_job_postings_source_external")
        batch.drop_column("external_id")
