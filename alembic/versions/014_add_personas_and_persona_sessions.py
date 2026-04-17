"""Add personas table and link chat_sessions to personas.

Revision ID: 014
Revises: 013
Create Date: 2026-04-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "personas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("persona_prompt", sa.Text(), nullable=False),
        sa.Column("style_notes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("exemplar_chunk_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False, server_default=sa.text("'{}'::uuid[]")),
        sa.Column("source_chunk_count", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("generated_by_model", sa.String(length=128), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("refresh_after_videos", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("videos_at_generation", sa.Integer(), nullable=False),
        sa.UniqueConstraint("scope_type", "scope_id", name="uq_personas_scope"),
    )

    op.create_index("idx_personas_scope", "personas", ["scope_type", "scope_id"])

    op.add_column(
        "chat_sessions",
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_chat_sessions_persona",
        "chat_sessions",
        "personas",
        ["persona_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_chat_sessions_persona", "chat_sessions", ["persona_id"])


def downgrade() -> None:
    op.drop_index("idx_chat_sessions_persona", table_name="chat_sessions")
    op.drop_constraint("fk_chat_sessions_persona", "chat_sessions", type_="foreignkey")
    op.drop_column("chat_sessions", "persona_id")

    op.drop_index("idx_personas_scope", table_name="personas")
    op.drop_table("personas")
