"""Enforce one active pipeline attempt per video at the database level.

Revision ID: 010
Revises: 009
Create Date: 2026-04-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_jobs_pipeline_one_active_attempt",
        "jobs",
        ["video_id"],
        unique=True,
        postgresql_where=sa.text(
            "video_id IS NOT NULL AND job_type = 'pipeline' AND status IN ('pending', 'queued', 'running')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_pipeline_one_active_attempt", table_name="jobs")
