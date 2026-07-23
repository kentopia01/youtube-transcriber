"""retain the most recent subscription polling error

Revision ID: 022
Revises: 021
Create Date: 2026-07-22
"""

from alembic import op
import sqlalchemy as sa


revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_subscriptions",
        sa.Column("last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("channel_subscriptions", "last_error")
