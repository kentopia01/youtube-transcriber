"""add reader annotations

Revision ID: 020
Revises: 019
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reader_annotations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("digest_lane_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("annotation_type", sa.String(24), nullable=False),
        sa.Column("block_anchor", sa.String(96), nullable=False),
        sa.Column("start_timestamp_seconds", sa.Float(), nullable=False),
        sa.Column("end_timestamp_seconds", sa.Float(), nullable=False),
        sa.Column("start_offset", sa.Integer(), server_default="0", nullable=False),
        sa.Column("end_offset", sa.Integer(), server_default="0", nullable=False),
        sa.Column("selected_text_snapshot", sa.Text(), server_default="", nullable=False),
        sa.Column("note_text", sa.Text(), nullable=True),
        sa.Column("context_before", sa.String(240), nullable=True),
        sa.Column("context_after", sa.String(240), nullable=True),
        sa.Column("reconciliation_status", sa.String(24), server_default="attached", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("annotation_type IN ('highlight', 'note', 'bookmark')", name="ck_reader_annotations_type"),
        sa.CheckConstraint("start_timestamp_seconds >= 0 AND end_timestamp_seconds >= start_timestamp_seconds", name="ck_reader_annotations_timestamps"),
        sa.CheckConstraint("start_offset >= 0 AND end_offset >= start_offset", name="ck_reader_annotations_offsets"),
        sa.CheckConstraint("reconciliation_status IN ('attached', 'reattached', 'orphaned')", name="ck_reader_annotations_reconciliation"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["digest_lane_id"], ["digest_lanes.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_reader_annotations_video_created", "reader_annotations", ["video_id", "created_at"])
    op.create_index("ix_reader_annotations_lane_created", "reader_annotations", ["digest_lane_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_reader_annotations_lane_created", table_name="reader_annotations")
    op.drop_index("ix_reader_annotations_video_created", table_name="reader_annotations")
    op.drop_table("reader_annotations")
