import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Persona(Base):
    """A generated persona for some scope (channel | advisor | speaker).

    scope_type='channel' is the only scope used in v1. Later scope types
    (`advisor`, `channel_role`, `speaker`) drop in without schema changes —
    rows, not migrations.
    """

    __tablename__ = "personas"
    __table_args__ = (
        UniqueConstraint("scope_type", "scope_id", name="uq_personas_scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    persona_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    style_notes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    exemplar_chunk_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list
    )
    source_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    generated_by_model: Mapped[str] = mapped_column(String(128), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    refresh_after_videos: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    videos_at_generation: Mapped[int] = mapped_column(Integer, nullable=False)
