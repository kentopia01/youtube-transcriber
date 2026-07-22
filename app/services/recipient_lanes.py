from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import settings
from app.models.digest_lane import (
    LANE_ROLE_ADMIN,
    LANE_ROLE_RESTRICTED,
    DigestLane,
)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class LaneAccess:
    telegram_user_id: int
    allowed: bool
    role: str | None
    lane: DigestLane | None
    reason: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.allowed and self.role == LANE_ROLE_ADMIN

    @property
    def is_restricted(self) -> bool:
        return self.allowed and self.role == LANE_ROLE_RESTRICTED


def slugify_lane_label(label: str) -> str:
    slug = _SLUG_RE.sub("-", label.strip().lower()).strip("-")
    if not slug:
        raise ValueError("lane label must contain a letter or number")
    return slug[:128]


async def get_lane_by_telegram_user(
    db: AsyncSession, telegram_user_id: int
) -> DigestLane | None:
    result = await db.execute(
        select(DigestLane).where(DigestLane.telegram_user_id == telegram_user_id)
    )
    return result.scalar_one_or_none()


async def find_digest_lane(db: AsyncSession, query: str) -> DigestLane | None:
    value = query.strip().lower()
    if not value:
        return None
    result = await db.execute(select(DigestLane).order_by(DigestLane.slug))
    lanes = list(result.scalars().all())
    for lane in lanes:
        if value in {lane.slug.lower(), lane.label.lower(), str(lane.telegram_user_id)}:
            return lane
    for lane in lanes:
        if value in lane.slug.lower() or value in lane.label.lower():
            return lane
    return None


async def resolve_lane_access(
    db: AsyncSession,
    telegram_user_id: int,
    *,
    telegram_chat_id: int | None = None,
    allowed_users: list[int] | None = None,
    admin_users: list[int] | None = None,
) -> LaneAccess:
    """Resolve allowlist, lane, and capability state without broadening access."""
    allowed_ids = set(
        settings.telegram_allowed_users if allowed_users is None else allowed_users
    )
    admin_ids = set(
        settings.telegram_admin_users if admin_users is None else admin_users
    )
    if telegram_user_id not in allowed_ids:
        return LaneAccess(
            telegram_user_id=telegram_user_id,
            allowed=False,
            role=None,
            lane=None,
            reason="not_allowlisted",
        )

    lane = await get_lane_by_telegram_user(db, telegram_user_id)
    if lane is None:
        # Preserve existing trusted-operator access during rollout, but fail
        # closed for restricted recipients until their lane is provisioned.
        if telegram_user_id in admin_ids:
            return LaneAccess(
                telegram_user_id=telegram_user_id,
                allowed=True,
                role=LANE_ROLE_ADMIN,
                lane=None,
                reason="admin_lane_not_provisioned",
            )
        return LaneAccess(
            telegram_user_id=telegram_user_id,
            allowed=False,
            role=None,
            lane=None,
            reason="lane_not_provisioned",
        )

    role = LANE_ROLE_ADMIN if telegram_user_id in admin_ids else lane.role
    if telegram_chat_id is not None and lane.telegram_chat_id != telegram_chat_id:
        lane.telegram_chat_id = telegram_chat_id
        await db.commit()
        await db.refresh(lane)

    return LaneAccess(
        telegram_user_id=telegram_user_id,
        allowed=True,
        role=role,
        lane=lane,
    )


def provision_digest_lane(
    db: Session,
    *,
    label: str,
    telegram_user_id: int,
    role: str,
    telegram_chat_id: int | None = None,
    timezone: str = "Asia/Singapore",
) -> DigestLane:
    if role not in {LANE_ROLE_ADMIN, LANE_ROLE_RESTRICTED}:
        raise ValueError(f"unsupported lane role: {role}")
    lane = db.scalar(
        select(DigestLane).where(DigestLane.telegram_user_id == telegram_user_id)
    )
    if lane is None:
        lane = DigestLane(
            label=label.strip(),
            slug=slugify_lane_label(label),
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            timezone=timezone,
            role=role,
        )
        db.add(lane)
    else:
        lane.label = label.strip()
        lane.slug = slugify_lane_label(label)
        lane.role = role
        lane.timezone = timezone
        if telegram_chat_id is not None:
            lane.telegram_chat_id = telegram_chat_id
    db.commit()
    db.refresh(lane)
    return lane


__all__ = [
    "LaneAccess",
    "find_digest_lane",
    "get_lane_by_telegram_user",
    "provision_digest_lane",
    "resolve_lane_access",
    "slugify_lane_label",
]
