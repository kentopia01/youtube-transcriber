import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id"), nullable=False
    )
    batch_number: Mapped[int] = mapped_column(Integer, nullable=False)
    total_batches: Mapped[int] = mapped_column(Integer, nullable=False)
    total_videos: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_videos: Mapped[int] = mapped_column(Integer, default=0)
    failed_videos: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    channel = relationship("Channel", back_populates="batches")
    jobs = relationship("Job", backref="batch")
