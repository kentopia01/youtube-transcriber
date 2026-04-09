"""Add pipeline observability fields for T008.

Revision ID: 013
Revises: 012
Create Date: 2026-04-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("current_stage_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("last_stage_ended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("last_ended_stage", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("attempt_creation_reason", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("worker_hostname", sa.String(length=255), nullable=True))
    op.add_column("jobs", sa.Column("worker_task_id", sa.String(length=255), nullable=True))
    op.add_column("jobs", sa.Column("last_artifact_check_result", sa.JSON(), nullable=True))

    op.execute(
        """
        UPDATE jobs
        SET current_stage_started_at = COALESCE(stage_updated_at, started_at, created_at)
        WHERE job_type = 'pipeline' AND current_stage IS NOT NULL
        """
    )

    op.create_index(
        "idx_jobs_pipeline_worker_lookup",
        "jobs",
        ["job_type", "status", "worker_hostname", "current_stage", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_jobs_pipeline_worker_lookup", table_name="jobs")
    op.drop_column("jobs", "last_artifact_check_result")
    op.drop_column("jobs", "worker_task_id")
    op.drop_column("jobs", "worker_hostname")
    op.drop_column("jobs", "attempt_creation_reason")
    op.drop_column("jobs", "last_ended_stage")
    op.drop_column("jobs", "last_stage_ended_at")
    op.drop_column("jobs", "current_stage_started_at")
