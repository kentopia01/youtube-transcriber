import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Transcription(Base):
    __tablename__ = "transcriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("videos.id"), unique=True, nullable=False
    )
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    model_size: Mapped[str | None] = mapped_column(String(32), nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processing_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    video = relationship("Video", back_populates="transcription")
    segments = relationship(
        "TranscriptionSegment", back_populates="transcription", order_by="TranscriptionSegment.segment_index"
    )
    embedding_chunks = relationship("EmbeddingChunk", back_populates="transcription")
