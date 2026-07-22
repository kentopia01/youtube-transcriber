from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.lane_digest import deliver_lane_digest, gather_lane_digest_inputs


class _DigestDB:
    def __init__(self, items, scalar_values=(2, 1)):
        result = MagicMock()
        result.scalars.return_value.all.return_value = list(items)
        self.execute = AsyncMock(return_value=result)
        self.scalar_values = list(scalar_values)
        self.commit = AsyncMock()

    async def scalar(self, statement):
        return self.scalar_values.pop(0)


def _lane(*, chat_id=123):
    return SimpleNamespace(
        id=uuid.uuid4(),
        label="Personal lane",
        slug="personal-lane",
        telegram_chat_id=chat_id,
        digest_enabled=True,
    )


def _item(lane_id, title, *, video_status="completed", job_status=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        lane_id=lane_id,
        video_id=uuid.uuid4(),
        video=SimpleNamespace(title=title, status=video_status),
        processing_job=(
            SimpleNamespace(status=job_status) if job_status is not None else None
        ),
        digest_delivered_at=None,
        dismissed_at=None,
        first_seen_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_gather_defensively_excludes_other_lane_items():
    lane = _lane()
    own = _item(lane.id, "Own completed video")
    other = _item(uuid.uuid4(), "Other lane secret")
    db = _DigestDB([own, other])

    inputs = await gather_lane_digest_inputs(db, lane)

    assert [item.video.title for item in inputs.completed_items] == [
        "Own completed video"
    ]


@pytest.mark.asyncio
async def test_delivery_targets_only_lane_chat_and_marks_own_completed_items():
    lane = _lane(chat_id=39026195)
    completed = _item(lane.id, "Ready video")
    active = _item(
        lane.id,
        "Processing video",
        video_status="processing",
        job_status="running",
    )
    db = _DigestDB([completed, active])
    sender = AsyncMock(return_value=True)

    result = await deliver_lane_digest(db, lane, sender=sender)

    assert result == {
        "status": "sent",
        "lane_id": str(lane.id),
        "completed": 1,
        "active": 1,
        "failed": 0,
    }
    sender.assert_awaited_once()
    assert sender.call_args.args[0] == 39026195
    text = sender.call_args.args[1]
    assert "Ready video" in text
    assert "Processing video" in text
    assert completed.digest_delivered_at is not None
    assert active.digest_delivered_at is None
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_lane_without_start_never_attempts_delivery():
    lane = _lane(chat_id=None)
    db = _DigestDB([])
    sender = AsyncMock(return_value=True)

    result = await deliver_lane_digest(db, lane, sender=sender)

    assert result["status"] == "awaiting_start"
    sender.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_send_does_not_mark_digest_items_delivered():
    lane = _lane()
    completed = _item(lane.id, "Ready video")
    db = _DigestDB([completed])

    result = await deliver_lane_digest(
        db,
        lane,
        sender=AsyncMock(return_value=False),
    )

    assert result["status"] == "delivery_failed"
    assert completed.digest_delivered_at is None
    db.commit.assert_not_awaited()
