import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


PIPELINE_ACTIVE_STATUSES = {"pending", "queued", "running"}
PIPELINE_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("videos.id"), nullable=True
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id"), nullable=True
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_stage_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_stage_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ended_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_number: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default=text("1"),
        nullable=False,
    )
    supersedes_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    attempt_creation_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    worker_hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    worker_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_artifact_check_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0)
    progress_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_signature: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_signature_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    recovery_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recovery_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden_from_queue: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    hidden_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    video = relationship("Video", back_populates="jobs")

    @property
    def display_name(self) -> str:
        if self.video and self.video.title:
            return self.video.title[:60] + ("..." if len(self.video.title) > 60 else "")
        return self.job_type

    @property
    def lifecycle_status(self) -> str:
        return self.status

    @property
    def attempt_state(self) -> str | None:
        if self.job_type != "pipeline":
            return None

        if self.hidden_reason == "superseded" and self.superseded_by_job_id is not None:
            return "superseded"

        if self.status in PIPELINE_ACTIVE_STATUSES:
            return "active"

        if self.status in PIPELINE_TERMINAL_STATUSES:
            return "terminal"

        return "unknown"

    @property
    def manual_review_required(self) -> bool:
        return self.recovery_status == "manual_review"
