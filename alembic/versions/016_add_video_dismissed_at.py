"""Add videos.dismissed_at + dismissed_reason for the ops-view cleanup.

Revision ID: 016
Revises: 015
Create Date: 2026-04-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "videos",
        sa.Column("dismissed_reason", sa.Text(), nullable=True),
    )
    # Partial index: we only ever query "not dismissed" in live views, and
    # dismissing is a rare write, so keep the index scanning only the active
    # subset.
    op.create_index(
        "idx_videos_dismissed_at_null",
        "videos",
        ["dismissed_at"],
        postgresql_where=sa.text("dismissed_at IS NULL"),
    )

    # One-time cleanup: dismiss the 25 legacy backfill failures — videos in
    # channels that are no longer subscribed. Reversible via /undismiss.
    op.execute(
        """
        UPDATE videos v
        SET dismissed_at = NOW(),
            dismissed_reason = 'legacy-backfill-failure: reaped during Apr 18 backfill'
        WHERE v.status = 'failed'
          AND v.created_at < '2026-04-19'::date
          AND (
            v.channel_id IS NULL
            OR v.channel_id NOT IN (
                SELECT channel_id FROM channel_subscriptions WHERE enabled = true
            )
          )
        """
    )


def downgrade() -> None:
    op.drop_index("idx_videos_dismissed_at_null", table_name="videos")
    op.drop_column("videos", "dismissed_reason")
    op.drop_column("videos", "dismissed_at")
