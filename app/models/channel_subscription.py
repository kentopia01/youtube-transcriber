import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ChannelSubscription(Base):
    """Watchlist row — the system polls this channel nightly and auto-ingests new uploads."""

    __tablename__ = "channel_subscriptions"
    __table_args__ = (UniqueConstraint("channel_id", name="uq_subs_channel"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    poll_frequency_hours: Mapped[int] = mapped_column(Integer, server_default="24", nullable=False)
    max_videos_per_poll: Mapped[int] = mapped_column(Integer, server_default="3", nullable=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_video_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default="{}", nullable=False
    )
    videos_ingested_today: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    daily_counter_reset_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    consecutive_failure_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    disabled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    channel = relationship("Channel", lazy="selectin")
