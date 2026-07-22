from __future__ import annotations

import asyncio
import inspect
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.digest_lane import DigestLane
from app.models.job import PIPELINE_ACTIVE_STATUSES
from app.models.lane_subscription import LaneSubscription
from app.models.lane_video_item import LaneVideoItem


LaneSender = Callable[[int, str], bool | Awaitable[bool]]


@dataclass(frozen=True)
class LaneDigestInput:
    lane: DigestLane
    window_start: datetime
    window_end: datetime
    enabled_subscriptions: int
    total_subscriptions: int
    completed_items: tuple[LaneVideoItem, ...]
    active_items: tuple[LaneVideoItem, ...]
    failed_items: tuple[LaneVideoItem, ...]


async def gather_lane_digest_inputs(
    db: AsyncSession,
    lane: DigestLane,
    *,
    window_hours: int = 24,
    now: datetime | None = None,
) -> LaneDigestInput:
    now = now or datetime.now(UTC)
    window_start = now - timedelta(hours=window_hours)
    items = list(
        (
            await db.execute(
                select(LaneVideoItem)
                .options(
                    selectinload(LaneVideoItem.video),
                    selectinload(LaneVideoItem.processing_job),
                )
                .where(
                    LaneVideoItem.lane_id == lane.id,
                    LaneVideoItem.dismissed_at.is_(None),
                    LaneVideoItem.first_seen_at >= window_start,
                )
                .order_by(LaneVideoItem.first_seen_at.desc())
            )
        ).scalars().all()
    )
    # Keep a defensive scope check so malformed test data or future query joins
    # cannot leak another lane into recipient-facing output.
    items = [item for item in items if item.lane_id == lane.id]

    completed: list[LaneVideoItem] = []
    active: list[LaneVideoItem] = []
    failed: list[LaneVideoItem] = []
    for item in items:
        video_status = getattr(item.video, "status", None)
        job_status = getattr(item.processing_job, "status", None)
        if video_status == "failed" or job_status == "failed":
            failed.append(item)
        elif video_status == "completed":
            if item.digest_delivered_at is None:
                completed.append(item)
        elif job_status in PIPELINE_ACTIVE_STATUSES or video_status in {
            "pending",
            "processing",
        }:
            active.append(item)

    total_subscriptions = int(
        await db.scalar(
            select(func.count(LaneSubscription.id)).where(
                LaneSubscription.lane_id == lane.id
            )
        )
        or 0
    )
    enabled_subscriptions = int(
        await db.scalar(
            select(func.count(LaneSubscription.id)).where(
                LaneSubscription.lane_id == lane.id,
                LaneSubscription.enabled.is_(True),
            )
        )
        or 0
    )
    return LaneDigestInput(
        lane=lane,
        window_start=window_start,
        window_end=now,
        enabled_subscriptions=enabled_subscriptions,
        total_subscriptions=total_subscriptions,
        completed_items=tuple(completed),
        active_items=tuple(active),
        failed_items=tuple(failed),
    )


def render_lane_digest(inputs: LaneDigestInput) -> str:
    lines = [
        f"YouTube digest — {inputs.lane.label}",
        (
            f"{inputs.enabled_subscriptions} active channel(s); "
            f"{len(inputs.completed_items)} ready, {len(inputs.active_items)} processing, "
            f"{len(inputs.failed_items)} need attention."
        ),
    ]
    if inputs.completed_items:
        lines.append("\nReady to read:")
        for item in inputs.completed_items[:10]:
            title = getattr(item.video, "title", None) or str(item.video_id)
            lines.append(f"• {title[:100]}")
    if inputs.active_items:
        lines.append("\nStill processing:")
        for item in inputs.active_items[:5]:
            title = getattr(item.video, "title", None) or str(item.video_id)
            lines.append(f"• {title[:100]}")
    if inputs.failed_items:
        lines.append("\nNeeds attention:")
        for item in inputs.failed_items[:5]:
            title = getattr(item.video, "title", None) or str(item.video_id)
            lines.append(f"• {title[:100]}")
    if not (inputs.completed_items or inputs.active_items or inputs.failed_items):
        lines.append("\nNothing new in this digest window.")
    return "\n".join(lines)


async def _default_sender(chat_id: int, text: str) -> bool:
    from app.services.telegram_notify import _send

    return await asyncio.to_thread(
        _send,
        chat_id,
        text,
        parse_mode=None,
        event_type="digest.lane",
        dedupe_key=f"lane_digest:{chat_id}:{datetime.now(UTC).date().isoformat()}",
    )


async def deliver_lane_digest(
    db: AsyncSession,
    lane: DigestLane,
    *,
    window_hours: int = 24,
    sender: LaneSender | None = None,
) -> dict[str, object]:
    if not lane.digest_enabled:
        return {"status": "disabled", "lane_id": str(lane.id)}
    if lane.telegram_chat_id is None:
        return {"status": "awaiting_start", "lane_id": str(lane.id)}

    inputs = await gather_lane_digest_inputs(db, lane, window_hours=window_hours)
    text = render_lane_digest(inputs)
    send = sender or _default_sender
    sent = send(lane.telegram_chat_id, text)
    if inspect.isawaitable(sent):
        sent = await sent
    if not sent:
        return {
            "status": "delivery_failed",
            "lane_id": str(lane.id),
            "completed": len(inputs.completed_items),
        }

    delivered_at = datetime.now(UTC)
    for item in inputs.completed_items:
        item.digest_delivered_at = delivered_at
    await db.commit()
    return {
        "status": "sent",
        "lane_id": str(lane.id),
        "completed": len(inputs.completed_items),
        "active": len(inputs.active_items),
        "failed": len(inputs.failed_items),
    }


__all__ = [
    "LaneDigestInput",
    "deliver_lane_digest",
    "gather_lane_digest_inputs",
    "render_lane_digest",
]
