import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


ANNOTATION_TYPES = frozenset({"highlight", "note", "bookmark"})


class ReaderAnnotation(Base):
    __tablename__ = "reader_annotations"
    __table_args__ = (
        CheckConstraint(
            "annotation_type IN ('highlight', 'note', 'bookmark')",
            name="ck_reader_annotations_type",
        ),
        CheckConstraint(
            "start_timestamp_seconds >= 0 AND end_timestamp_seconds >= start_timestamp_seconds",
            name="ck_reader_annotations_timestamps",
        ),
        CheckConstraint(
            "start_offset >= 0 AND end_offset >= start_offset",
            name="ck_reader_annotations_offsets",
        ),
        CheckConstraint(
            "reconciliation_status IN ('attached', 'reattached', 'orphaned')",
            name="ck_reader_annotations_reconciliation",
        ),
        Index("ix_reader_annotations_video_created", "video_id", "created_at"),
        Index("ix_reader_annotations_lane_created", "digest_lane_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    digest_lane_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("digest_lanes.id", ondelete="CASCADE"), nullable=True
    )
    annotation_type: Mapped[str] = mapped_column(String(24), nullable=False)
    block_anchor: Mapped[str] = mapped_column(String(96), nullable=False)
    start_timestamp_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_timestamp_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    selected_text_snapshot: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    note_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_before: Mapped[str | None] = mapped_column(String(240), nullable=True)
    context_after: Mapped[str | None] = mapped_column(String(240), nullable=True)
    reconciliation_status: Mapped[str] = mapped_column(
        String(24), default="attached", server_default="attached", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    video = relationship("Video", back_populates="reader_annotations")
    digest_lane = relationship("DigestLane", back_populates="reader_annotations")
