"""Initial schema with all tables

Revision ID: 001
Revises:
Create Date: 2026-03-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extensions are created by the init SQL script, but ensure they exist
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    op.execute("CREATE EXTENSION IF NOT EXISTS \"vector\"")

    # Channels
    op.create_table(
        "channels",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("youtube_channel_id", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("thumbnail_url", sa.String(512), nullable=True),
        sa.Column("video_count", sa.Integer, default=0),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Videos
    op.create_table(
        "videos",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("youtube_video_id", sa.String(32), unique=True, nullable=False),
        sa.Column("channel_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("channels.id"), nullable=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("thumbnail_url", sa.String(512), nullable=True),
        sa.Column("audio_file_path", sa.String(512), nullable=True),
        sa.Column("status", sa.String(32), default="pending", nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Transcriptions
    op.create_table(
        "transcriptions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("video_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("videos.id"), unique=True, nullable=False),
        sa.Column("full_text", sa.Text, nullable=False),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("model_size", sa.String(32), nullable=True),
        sa.Column("word_count", sa.Integer, nullable=True),
        sa.Column("processing_time_seconds", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Transcription segments
    op.create_table(
        "transcription_segments",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("transcription_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("transcriptions.id"), nullable=False),
        sa.Column("segment_index", sa.Integer, nullable=False),
        sa.Column("start_time", sa.Float, nullable=False),
        sa.Column("end_time", sa.Float, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
    )

    # Summaries
    op.create_table(
        "summaries",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("video_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("videos.id"), unique=True, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("prompt_tokens", sa.Integer, nullable=True),
        sa.Column("completion_tokens", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Embedding chunks
    op.create_table(
        "embedding_chunks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("transcription_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("transcriptions.id"), nullable=False),
        sa.Column("video_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("videos.id"), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("chunk_text", sa.Text, nullable=False),
        sa.Column("start_time", sa.Float, nullable=True),
        sa.Column("end_time", sa.Float, nullable=True),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # HNSW index for cosine similarity search
    op.execute(
        "CREATE INDEX idx_embedding_chunks_embedding ON embedding_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    # Batches
    op.create_table(
        "batches",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("channel_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("batch_number", sa.Integer, nullable=False),
        sa.Column("total_batches", sa.Integer, nullable=False),
        sa.Column("total_videos", sa.Integer, nullable=False),
        sa.Column("completed_videos", sa.Integer, default=0),
        sa.Column("failed_videos", sa.Integer, default=0),
        sa.Column("status", sa.String(32), default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Jobs
    op.create_table(
        "jobs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("video_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("videos.id"), nullable=True),
        sa.Column("channel_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("channels.id"), nullable=True),
        sa.Column("batch_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("batches.id"), nullable=True),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), default="pending", nullable=False),
        sa.Column("progress_pct", sa.Float, default=0.0),
        sa.Column("progress_message", sa.String(512), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("batches")
    op.execute("DROP INDEX IF EXISTS idx_embedding_chunks_embedding")
    op.drop_table("embedding_chunks")
    op.drop_table("summaries")
    op.drop_table("transcription_segments")
    op.drop_table("transcriptions")
    op.drop_table("videos")
    op.drop_table("channels")
