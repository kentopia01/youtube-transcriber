"""Add job visibility metadata for superseded failed attempts

Revision ID: 008
Revises: 007
Create Date: 2026-04-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "hidden_from_queue",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("jobs", sa.Column("hidden_reason", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("superseded_by_job_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.create_index(
        "idx_jobs_failed_visible",
        "jobs",
        ["status", "hidden_from_queue", "completed_at"],
    )
    op.create_index(
        "idx_jobs_hidden_superseded_cleanup",
        "jobs",
        ["status", "hidden_from_queue", "hidden_reason", "hidden_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_jobs_hidden_superseded_cleanup", table_name="jobs")
    op.drop_index("idx_jobs_failed_visible", table_name="jobs")

    op.drop_column("jobs", "superseded_by_job_id")
    op.drop_column("jobs", "hidden_at")
    op.drop_column("jobs", "hidden_reason")
    op.drop_column("jobs", "hidden_from_queue")
