"""Add tsvector column for hybrid search (BM25 + vector RRF)

Revision ID: 004
Revises: 003
Create Date: 2026-03-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add tsvector column
    op.add_column(
        "embedding_chunks",
        sa.Column("search_vector", sa.dialects.postgresql.TSVECTOR, nullable=True),
    )

    # Create GIN index for fast full-text search
    op.execute(
        "CREATE INDEX idx_embedding_chunks_search_vector "
        "ON embedding_chunks USING gin (search_vector)"
    )

    # Create trigger to auto-populate search_vector on INSERT/UPDATE
    op.execute("""
        CREATE OR REPLACE FUNCTION embedding_chunks_search_vector_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('english', COALESCE(NEW.chunk_text, ''));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER embedding_chunks_search_vector_trigger
        BEFORE INSERT OR UPDATE OF chunk_text ON embedding_chunks
        FOR EACH ROW
        EXECUTE FUNCTION embedding_chunks_search_vector_update();
    """)

    # Backfill existing rows
    op.execute(
        "UPDATE embedding_chunks SET search_vector = to_tsvector('english', COALESCE(chunk_text, ''))"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS embedding_chunks_search_vector_trigger ON embedding_chunks")
    op.execute("DROP FUNCTION IF EXISTS embedding_chunks_search_vector_update()")
    op.execute("DROP INDEX IF EXISTS idx_embedding_chunks_search_vector")
    op.drop_column("embedding_chunks", "search_vector")
