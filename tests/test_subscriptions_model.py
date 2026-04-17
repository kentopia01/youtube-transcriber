"""Tests for ChannelSubscription model + migration auto-seed smoke."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.models import ChannelSubscription, Video


class TestChannelSubscriptionDefaults:
    def test_default_attributes_construct_cleanly(self):
        sub = ChannelSubscription(
            channel_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        )
        assert sub.channel_id is not None
        # Defaults are DB-side, so instance fields stay None until flush/refresh.
        # We just ensure the model accepts the minimal construction.

    def test_can_set_all_fields(self):
        sub = ChannelSubscription(
            channel_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            enabled=False,
            poll_frequency_hours=12,
            max_videos_per_poll=5,
            last_polled_at=datetime.now(UTC),
            last_seen_video_ids=["a", "b"],
            videos_ingested_today=2,
            consecutive_failure_count=1,
            disabled_reason="test",
        )
        assert sub.enabled is False
        assert sub.poll_frequency_hours == 12
        assert sub.last_seen_video_ids == ["a", "b"]


class TestVideoCompressionFields:
    def test_new_attributes_exist(self):
        v = Video(
            youtube_video_id="abc123",
            title="x",
            url="https://youtube.com/watch?v=abc123",
        )
        # New nullable fields should default to None before commit
        assert hasattr(v, "last_activity_at")
        assert hasattr(v, "compressed_at")
        assert v.last_activity_at is None
        assert v.compressed_at is None
