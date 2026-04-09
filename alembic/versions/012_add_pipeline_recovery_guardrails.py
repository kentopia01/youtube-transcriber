"""Add pipeline recovery metadata for Phase 3.

Revision ID: 012
Revises: 011
Create Date: 2026-04-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("failure_signature", sa.String(length=255), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("failure_signature_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("jobs", sa.Column("recovery_status", sa.String(length=32), nullable=True))
    op.add_column("jobs", sa.Column("recovery_reason", sa.Text(), nullable=True))

    op.execute(
        """
        UPDATE jobs
        SET last_activity_at = COALESCE(stage_updated_at, started_at, created_at)
        WHERE job_type = 'pipeline'
        """
    )

    op.create_index(
        "idx_jobs_pipeline_recovery_lookup",
        "jobs",
        ["video_id", "job_type", "status", "recovery_status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_jobs_pipeline_recovery_lookup", table_name="jobs")
    op.drop_column("jobs", "recovery_reason")
    op.drop_column("jobs", "recovery_status")
    op.drop_column("jobs", "failure_signature_count")
    op.drop_column("jobs", "failure_signature")
    op.drop_column("jobs", "last_activity_at")
