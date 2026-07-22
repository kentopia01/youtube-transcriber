import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


READER_STATUS_UNREAD = "unread"
READER_STATUS_READING = "reading"
READER_STATUS_LATER = "later"
READER_STATUS_FINISHED = "finished"
READER_STATUS_ARCHIVED = "archived"
READER_STATUSES = frozenset(
    {
        READER_STATUS_UNREAD,
        READER_STATUS_READING,
        READER_STATUS_LATER,
        READER_STATUS_FINISHED,
        READER_STATUS_ARCHIVED,
    }
)


class ReaderState(Base):
    """Durable reading state, independent of video and pipeline lifecycle state.

    ``digest_lane_id`` deliberately reuses the T049 recipient identity boundary.
    A NULL owner represents the current trusted local reader; the partial unique
    index makes that temporary ownership mode deterministic and migration-safe.
    """

    __tablename__ = "reader_states"
    __table_args__ = (
        UniqueConstraint(
            "digest_lane_id", "video_id", name="uq_reader_states_lane_video"
        ),
        CheckConstraint(
            "status IN ('unread', 'reading', 'later', 'finished', 'archived')",
            name="ck_reader_states_status",
        ),
        CheckConstraint(
            "progress_pct >= 0 AND progress_pct <= 100",
            name="ck_reader_states_progress_pct",
        ),
        CheckConstraint(
            "last_timestamp_seconds IS NULL OR last_timestamp_seconds >= 0",
            name="ck_reader_states_last_timestamp",
        ),
        Index(
            "uq_reader_states_local_video",
            "video_id",
            unique=True,
            postgresql_where=text("digest_lane_id IS NULL"),
        ),
        Index("ix_reader_states_status_activity", "status", "last_read_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    digest_lane_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("digest_lanes.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default=READER_STATUS_UNREAD, server_default=READER_STATUS_UNREAD, nullable=False
    )
    progress_pct: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0", nullable=False
    )
    last_block_anchor: Mapped[str | None] = mapped_column(String(96), nullable=True)
    last_timestamp_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    video = relationship("Video", back_populates="reader_states")
    digest_lane = relationship("DigestLane", back_populates="reader_states")
