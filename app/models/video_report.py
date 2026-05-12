import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


SUMMARY_REPORT_TYPE = "summary_report"


class VideoReport(Base):
    """Current deliverable summary report for one video.

    ``video_reports`` intentionally stores one current summary report row per
    video. ``report_type`` is a canonical historical/type label, not a
    uniqueness dimension that permits multiple rows for the same video.
    """

    __tablename__ = "video_reports"
    __table_args__ = (UniqueConstraint("video_id", name="uq_video_reports_video_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("videos.id"), nullable=False
    )
    report_type: Mapped[str] = mapped_column(
        String(64), default=SUMMARY_REPORT_TYPE, nullable=False
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    html_content: Mapped[str] = mapped_column(Text, nullable=False)
    markdown_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    video = relationship("Video", back_populates="report")


__all__ = ["SUMMARY_REPORT_TYPE", "VideoReport"]
