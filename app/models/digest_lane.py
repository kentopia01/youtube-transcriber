import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


LANE_ROLE_ADMIN = "admin"
LANE_ROLE_RESTRICTED = "restricted"
LANE_ROLES = frozenset({LANE_ROLE_ADMIN, LANE_ROLE_RESTRICTED})


class DigestLane(Base):
    """Recipient identity and delivery boundary for scoped Telegram digests."""

    __tablename__ = "digest_lanes"
    __table_args__ = (
        UniqueConstraint("label", name="uq_digest_lanes_label"),
        UniqueConstraint("slug", name="uq_digest_lanes_slug"),
        UniqueConstraint("telegram_user_id", name="uq_digest_lanes_telegram_user_id"),
        UniqueConstraint("telegram_chat_id", name="uq_digest_lanes_telegram_chat_id"),
        CheckConstraint(
            "role IN ('admin', 'restricted')",
            name="ck_digest_lanes_role",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(64), default="Asia/Singapore", server_default="Asia/Singapore", nullable=False
    )
    digest_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(32), default=LANE_ROLE_RESTRICTED, server_default=LANE_ROLE_RESTRICTED, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    subscriptions = relationship(
        "LaneSubscription", back_populates="lane", cascade="all, delete-orphan"
    )
    video_items = relationship(
        "LaneVideoItem", back_populates="lane", cascade="all, delete-orphan"
    )
    reader_states = relationship(
        "ReaderState", back_populates="digest_lane", cascade="all, delete-orphan"
    )
    reader_annotations = relationship(
        "ReaderAnnotation", back_populates="digest_lane", cascade="all, delete-orphan"
    )

    @property
    def is_admin(self) -> bool:
        return self.role == LANE_ROLE_ADMIN
