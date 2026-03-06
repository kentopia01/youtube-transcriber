"""Upgrade embedding column to 768d (nomic-embed-text-v1.5) and add speaker column

Revision ID: 003
Revises: 002
Create Date: 2026-03-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Truncate existing embeddings — they will be re-embedded with the new model
    op.execute("TRUNCATE TABLE embedding_chunks")

    # Drop the old HNSW index (it's bound to vector(384))
    op.execute("DROP INDEX IF EXISTS idx_embedding_chunks_embedding")

    # Resize embedding column from vector(384) to vector(768)
    op.execute("ALTER TABLE embedding_chunks ALTER COLUMN embedding TYPE vector(768)")

    # Add speaker column
    op.add_column(
        'embedding_chunks',
        sa.Column('speaker', sa.String(32), nullable=True),
    )

    # Recreate HNSW index for the new dimension
    op.execute(
        "CREATE INDEX idx_embedding_chunks_embedding ON embedding_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_column('embedding_chunks', 'speaker')
    op.execute("DROP INDEX IF EXISTS idx_embedding_chunks_embedding")
    op.execute("TRUNCATE TABLE embedding_chunks")
    op.execute("ALTER TABLE embedding_chunks ALTER COLUMN embedding TYPE vector(384)")
    op.execute(
        "CREATE INDEX idx_embedding_chunks_embedding ON embedding_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )
