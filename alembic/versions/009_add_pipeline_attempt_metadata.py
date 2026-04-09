"""Add pipeline attempt metadata and lineage fields to jobs.

Revision ID: 009
Revises: 008
Create Date: 2026-04-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "jobs",
        sa.Column("supersedes_job_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.create_index(
        "idx_jobs_pipeline_attempt_lineage",
        "jobs",
        ["video_id", "job_type", "attempt_number"],
    )
    op.create_index(
        "idx_jobs_pipeline_active_lookup",
        "jobs",
        ["video_id", "job_type", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_jobs_pipeline_active_lookup", table_name="jobs")
    op.drop_index("idx_jobs_pipeline_attempt_lineage", table_name="jobs")

    op.drop_column("jobs", "supersedes_job_id")
    op.drop_column("jobs", "attempt_number")
