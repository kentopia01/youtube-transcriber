"""Add channel_subscriptions, video activity/compression fields, llm_usage source tag.

Revision ID: 015
Revises: 014
Create Date: 2026-04-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # channel_subscriptions
    op.create_table(
        "channel_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("poll_frequency_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("max_videos_per_poll", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_video_ids", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("videos_ingested_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("daily_counter_reset_at", sa.Date(), nullable=True),
        sa.Column("consecutive_failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("disabled_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("channel_id", name="uq_subs_channel"),
    )
    op.create_index("idx_subs_enabled_last_poll", "channel_subscriptions", ["enabled", "last_polled_at"])

    # video compression + activity
    op.add_column("videos", sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("videos", sa.Column("compressed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE videos SET last_activity_at = COALESCE(updated_at, created_at)"
    )
    op.create_index(
        "idx_videos_activity_compression",
        "videos",
        ["last_activity_at", "compressed_at"],
    )

    # llm_usage source tag — supports separated auto-ingest budget
    op.add_column("llm_usage", sa.Column("source", sa.String(length=32), nullable=True))
    op.create_index("idx_llm_usage_source_created", "llm_usage", ["source", "created_at"])

    # Auto-seed: enable subscriptions for every existing channel that has at
    # least one completed video (active channels). Idempotent via unique(channel_id).
    op.execute(
        """
        INSERT INTO channel_subscriptions (channel_id, enabled)
        SELECT DISTINCT c.id, true
        FROM channels c
        JOIN videos v ON v.channel_id = c.id
        WHERE v.status = 'completed'
        ON CONFLICT (channel_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("idx_llm_usage_source_created", table_name="llm_usage")
    op.drop_column("llm_usage", "source")

    op.drop_index("idx_videos_activity_compression", table_name="videos")
    op.drop_column("videos", "compressed_at")
    op.drop_column("videos", "last_activity_at")

    op.drop_index("idx_subs_enabled_last_poll", table_name="channel_subscriptions")
    op.drop_table("channel_subscriptions")
