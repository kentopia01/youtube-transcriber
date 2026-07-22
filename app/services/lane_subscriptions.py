from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.channel import Channel
from app.models.lane_subscription import LaneSubscription


async def list_lane_subscriptions(
    db: AsyncSession, lane_id: uuid.UUID
) -> list[LaneSubscription]:
    result = await db.execute(
        select(LaneSubscription)
        .options(selectinload(LaneSubscription.channel))
        .where(LaneSubscription.lane_id == lane_id)
        .order_by(LaneSubscription.created_at.desc())
    )
    return list(result.scalars().all())


async def get_lane_subscription_for_channel(
    db: AsyncSession,
    lane_id: uuid.UUID,
    channel_id: uuid.UUID,
) -> LaneSubscription | None:
    result = await db.execute(
        select(LaneSubscription).where(
            LaneSubscription.lane_id == lane_id,
            LaneSubscription.channel_id == channel_id,
        )
    )
    return result.scalar_one_or_none()


async def create_or_enable_lane_subscription(
    db: AsyncSession,
    lane_id: uuid.UUID,
    channel: Channel,
    *,
    poll_frequency_hours: int = 24,
    max_videos_per_poll: int = 3,
) -> LaneSubscription:
    subscription = await get_lane_subscription_for_channel(db, lane_id, channel.id)
    if subscription is None:
        subscription = LaneSubscription(
            lane_id=lane_id,
            channel_id=channel.id,
            enabled=True,
            poll_frequency_hours=poll_frequency_hours,
            max_videos_per_poll=max_videos_per_poll,
        )
        db.add(subscription)
    else:
        subscription.enabled = True
        subscription.disabled_reason = None
        subscription.poll_frequency_hours = poll_frequency_hours
        subscription.max_videos_per_poll = max_videos_per_poll
    await db.commit()
    await db.refresh(subscription)
    return subscription


async def disable_lane_subscription(
    db: AsyncSession,
    lane_id: uuid.UUID,
    channel_id: uuid.UUID,
    *,
    reason: str = "user_disabled",
) -> LaneSubscription | None:
    subscription = await get_lane_subscription_for_channel(db, lane_id, channel_id)
    if subscription is None:
        return None
    subscription.enabled = False
    subscription.disabled_reason = reason
    await db.commit()
    await db.refresh(subscription)
    return subscription


__all__ = [
    "create_or_enable_lane_subscription",
    "disable_lane_subscription",
    "get_lane_subscription_for_channel",
    "list_lane_subscriptions",
]
