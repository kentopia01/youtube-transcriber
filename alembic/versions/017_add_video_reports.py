"""add video reports

Revision ID: 017
Revises: 016
Create Date: 2026-05-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("html_content", sa.Text(), nullable=False),
        sa.Column("markdown_content", sa.Text(), nullable=True),
        sa.Column("artifact_path", sa.String(length=1024), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("delivery_status", sa.String(length=32), nullable=False),
        sa.Column("delivery_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("video_id", name="uq_video_reports_video_id"),
    )
    op.create_index("ix_video_reports_delivery_status", "video_reports", ["delivery_status"])


def downgrade() -> None:
    op.drop_index("ix_video_reports_delivery_status", table_name="video_reports")
    op.drop_table("video_reports")
