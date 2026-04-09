"""Add explicit pipeline stage tracking to jobs.

Revision ID: 011
Revises: 010
Create Date: 2026-04-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("current_stage", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("stage_updated_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        """
        UPDATE jobs
        SET
            current_stage = CASE
                WHEN status IN ('pending', 'queued') THEN 'queued'
                WHEN status = 'running' THEN CASE
                    WHEN progress_pct >= 93 THEN 'embed'
                    WHEN progress_pct >= 76 THEN 'summarize'
                    WHEN progress_pct >= 67 THEN 'cleanup'
                    WHEN progress_pct >= 52 THEN 'diarize'
                    WHEN progress_pct >= 30 THEN 'transcribe'
                    WHEN progress_pct > 0 THEN 'download'
                    ELSE 'queued'
                END
                WHEN status = 'completed' THEN 'completed'
                WHEN status = 'cancelled' THEN 'cancelled'
                WHEN status = 'failed' THEN CASE
                    WHEN progress_pct >= 93 THEN 'embed'
                    WHEN progress_pct >= 76 THEN 'summarize'
                    WHEN progress_pct >= 67 THEN 'cleanup'
                    WHEN progress_pct >= 52 THEN 'diarize'
                    WHEN progress_pct >= 30 THEN 'transcribe'
                    WHEN progress_pct > 0 THEN 'download'
                    ELSE 'queued'
                END
                ELSE NULL
            END,
            stage_updated_at = COALESCE(completed_at, started_at, created_at)
        WHERE job_type = 'pipeline'
        """
    )

    op.create_index(
        "idx_jobs_pipeline_stage_lookup",
        "jobs",
        ["job_type", "status", "current_stage", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_jobs_pipeline_stage_lookup", table_name="jobs")
    op.drop_column("jobs", "stage_updated_at")
    op.drop_column("jobs", "current_stage")
