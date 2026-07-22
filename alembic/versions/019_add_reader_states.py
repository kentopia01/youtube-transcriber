"""add durable reader state

Revision ID: 019
Revises: 018
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reader_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("digest_lane_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="unread", nullable=False),
        sa.Column("progress_pct", sa.Float(), server_default="0", nullable=False),
        sa.Column("last_block_anchor", sa.String(length=96), nullable=True),
        sa.Column("last_timestamp_seconds", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('unread', 'reading', 'later', 'finished', 'archived')",
            name="ck_reader_states_status",
        ),
        sa.CheckConstraint(
            "progress_pct >= 0 AND progress_pct <= 100",
            name="ck_reader_states_progress_pct",
        ),
        sa.CheckConstraint(
            "last_timestamp_seconds IS NULL OR last_timestamp_seconds >= 0",
            name="ck_reader_states_last_timestamp",
        ),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["digest_lane_id"], ["digest_lanes.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "digest_lane_id", "video_id", name="uq_reader_states_lane_video"
        ),
    )
    op.create_index(
        "uq_reader_states_local_video",
        "reader_states",
        ["video_id"],
        unique=True,
        postgresql_where=sa.text("digest_lane_id IS NULL"),
    )
    op.create_index(
        "ix_reader_states_status_activity",
        "reader_states",
        ["status", "last_read_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_reader_states_status_activity", table_name="reader_states")
    op.drop_index("uq_reader_states_local_video", table_name="reader_states")
    op.drop_table("reader_states")
