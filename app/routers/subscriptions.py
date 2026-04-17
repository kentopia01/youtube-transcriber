"""Channel subscription HTTP endpoints.

Backs the Telegram commands and any future web UI. Solo-user: no per-user
scoping — everything is owned by the single operator.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db
from app.models.channel import Channel
from app.services.channel_sync import get_or_create_channel
from app.services.subscriptions import (
    SubscriptionError,
    create_or_enable_subscription,
    disable_subscription,
    fetch_channel_feed,
    list_subscriptions,
)
from app.services.youtube import discover_channel_videos, is_channel_url

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


class SubscriptionCreate(BaseModel):
    url: str = Field(..., description="YouTube channel URL, handle, or channel id.")
    poll_frequency_hours: int = Field(
        default=settings.auto_ingest_poll_hours_default, ge=1, le=24 * 7
    )
    max_videos_per_poll: int = Field(
        default=settings.auto_ingest_max_videos_per_poll_default, ge=1, le=20
    )


class SubscriptionPatch(BaseModel):
    enabled: bool | None = None
    poll_frequency_hours: int | None = Field(default=None, ge=1, le=24 * 7)
    max_videos_per_poll: int | None = Field(default=None, ge=1, le=20)


def _serialize(sub, channel):
    return {
        "id": str(sub.id),
        "channel_id": str(sub.channel_id),
        "channel_name": channel.name if channel else None,
        "enabled": sub.enabled,
        "poll_frequency_hours": sub.poll_frequency_hours,
        "max_videos_per_poll": sub.max_videos_per_poll,
        "last_polled_at": sub.last_polled_at.isoformat() if sub.last_polled_at else None,
        "videos_ingested_today": sub.videos_ingested_today,
        "consecutive_failure_count": sub.consecutive_failure_count,
        "disabled_reason": sub.disabled_reason,
    }


@router.get("")
async def list_all(db: AsyncSession = Depends(get_db)):
    subs = await list_subscriptions(db)
    return {"subscriptions": [_serialize(s, s.channel) for s in subs]}


@router.post("")
async def create(data: SubscriptionCreate, db: AsyncSession = Depends(get_db)):
    url = data.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required.")
    if not is_channel_url(url):
        raise HTTPException(
            status_code=400,
            detail="Not a channel URL. Use a /@handle, /c/, /user/, or /channel/ link.",
        )

    # Discover channel metadata via yt-dlp (reuses existing flow)
    try:
        result = discover_channel_videos(url, max_videos=1)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Channel lookup failed: {exc}") from exc

    yt_id = result.get("channel_id")
    if not yt_id:
        raise HTTPException(status_code=400, detail="Could not resolve YouTube channel ID from URL.")

    channel = await get_or_create_channel(
        db,
        youtube_channel_id=yt_id,
        name=result.get("channel_name", "Unknown"),
        url=url,
        description=result.get("description"),
        thumbnail_url=result.get("thumbnail"),
    )
    if channel is None:
        raise HTTPException(status_code=500, detail="Could not create channel record.")

    # Sanity-check the RSS feed before persisting.
    try:
        await fetch_channel_feed(yt_id)
    except SubscriptionError as exc:
        raise HTTPException(status_code=400, detail=f"RSS feed unreachable: {exc}") from exc

    sub = await create_or_enable_subscription(
        db,
        channel,
        poll_frequency_hours=data.poll_frequency_hours,
        max_videos_per_poll=data.max_videos_per_poll,
    )
    return _serialize(sub, channel)


@router.patch("/{subscription_id}")
async def patch(
    subscription_id: uuid.UUID,
    data: SubscriptionPatch,
    db: AsyncSession = Depends(get_db),
):
    from app.models.channel_subscription import ChannelSubscription

    sub = await db.get(ChannelSubscription, subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if data.enabled is not None:
        sub.enabled = data.enabled
        if data.enabled:
            sub.disabled_reason = None
        else:
            sub.disabled_reason = "user_disabled"
    if data.poll_frequency_hours is not None:
        sub.poll_frequency_hours = data.poll_frequency_hours
    if data.max_videos_per_poll is not None:
        sub.max_videos_per_poll = data.max_videos_per_poll
    await db.commit()
    await db.refresh(sub)
    channel = await db.get(Channel, sub.channel_id)
    return _serialize(sub, channel)


@router.delete("/{subscription_id}")
async def delete(subscription_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    from app.models.channel_subscription import ChannelSubscription

    sub = await db.get(ChannelSubscription, subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    await db.delete(sub)
    await db.commit()
    return {"deleted": True, "subscription_id": str(subscription_id)}
