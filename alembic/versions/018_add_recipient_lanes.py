"""add recipient lanes

Revision ID: 018
Revises: 017
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "digest_lanes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("timezone", sa.String(length=64), server_default="Asia/Singapore", nullable=False),
        sa.Column("digest_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("role", sa.String(length=32), server_default="restricted", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'restricted')", name="ck_digest_lanes_role"),
        sa.UniqueConstraint("label", name="uq_digest_lanes_label"),
        sa.UniqueConstraint("slug", name="uq_digest_lanes_slug"),
        sa.UniqueConstraint("telegram_user_id", name="uq_digest_lanes_telegram_user_id"),
        sa.UniqueConstraint("telegram_chat_id", name="uq_digest_lanes_telegram_chat_id"),
    )

    op.create_table(
        "lane_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("lane_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("poll_frequency_hours", sa.Integer(), server_default="24", nullable=False),
        sa.Column("max_videos_per_poll", sa.Integer(), server_default="3", nullable=False),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_video_ids", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("videos_ingested_today", sa.Integer(), server_default="0", nullable=False),
        sa.Column("daily_counter_reset_at", sa.Date(), nullable=True),
        sa.Column("consecutive_failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("disabled_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["lane_id"], ["digest_lanes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("lane_id", "channel_id", name="uq_lane_subscriptions_lane_channel"),
    )
    op.create_index(
        "ix_lane_subscriptions_due",
        "lane_subscriptions",
        ["enabled", "last_polled_at"],
    )

    op.create_table(
        "lane_video_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("lane_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lane_subscription_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("processing_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(length=32), server_default="lane_poll", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("digest_delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["lane_id"], ["digest_lanes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["lane_subscription_id"], ["lane_subscriptions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["processing_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("lane_id", "video_id", name="uq_lane_video_items_lane_video"),
    )
    op.create_index(
        "ix_lane_video_items_digest_pending",
        "lane_video_items",
        ["lane_id", "digest_delivered_at", "dismissed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_lane_video_items_digest_pending", table_name="lane_video_items")
    op.drop_table("lane_video_items")
    op.drop_index("ix_lane_subscriptions_due", table_name="lane_subscriptions")
    op.drop_table("lane_subscriptions")
    op.drop_table("digest_lanes")
