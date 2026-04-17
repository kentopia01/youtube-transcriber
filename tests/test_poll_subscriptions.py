"""Tests for the poll_subscriptions task."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.subscriptions import FeedEntry
from app.tasks import poll_subscriptions as poll_module


def _sub(channel, **kw):
    defaults = dict(
        id=uuid.uuid4(),
        channel_id=channel.id,
        channel=channel,
        enabled=True,
        poll_frequency_hours=24,
        max_videos_per_poll=3,
        last_polled_at=None,
        last_seen_video_ids=[],
        videos_ingested_today=0,
        daily_counter_reset_at=None,
        consecutive_failure_count=0,
        disabled_reason=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _channel():
    return SimpleNamespace(
        id=uuid.UUID(int=42),
        name="Test Channel",
        youtube_channel_id="UC-test",
    )


class _DbStub:
    def __init__(self):
        self.committed = 0

    async def commit(self):
        self.committed += 1

    async def get(self, model, key):
        return None


class TestProcessOneSubscription:
    @pytest.mark.asyncio
    async def test_no_new_videos_marks_poll_and_exits(self, monkeypatch):
        channel = _channel()
        sub = _sub(channel, last_seen_video_ids=["aaa"])

        monkeypatch.setattr(
            poll_module, "fetch_channel_feed",
            AsyncMock(return_value=[FeedEntry("aaa", "t", "u", None)]),
        )

        db = _DbStub()
        out = await poll_module._process_one_subscription(db, sub, budget_remaining=10.0)
        assert out["new_videos_found"] == 0
        assert out["ingested"] == 0
        assert sub.last_polled_at is not None
        assert db.committed >= 1

    @pytest.mark.asyncio
    async def test_ingests_new_videos_up_to_cap(self, monkeypatch):
        channel = _channel()
        sub = _sub(channel, max_videos_per_poll=2)

        feed_entries = [
            FeedEntry(f"new{i}", f"title {i}", f"https://youtube.com/v={i}", None)
            for i in range(5)
        ]
        monkeypatch.setattr(
            poll_module, "fetch_channel_feed",
            AsyncMock(return_value=feed_entries),
        )

        submitted = []

        async def fake_submit(url, api_key=None):
            submitted.append(url)
            return {"job_id": str(uuid.uuid4()), "video_id": str(uuid.uuid4())}

        monkeypatch.setattr(poll_module, "_submit_video", fake_submit)
        monkeypatch.setattr(poll_module, "_tag_job_as_auto_ingest", AsyncMock())
        # Classifier accepts everything in this test
        monkeypatch.setattr(
            "app.services.video_classifier.classify_video_url",
            lambda url: __import__("app.services.video_classifier", fromlist=["ClassificationResult"]).ClassificationResult(True, None),
        )

        db = _DbStub()
        out = await poll_module._process_one_subscription(db, sub, budget_remaining=10.0)
        assert out["new_videos_found"] == 5
        assert out["ingested"] == 2
        assert sub.videos_ingested_today == 2
        assert out.get("rejected_by_filter") == 0

    @pytest.mark.asyncio
    async def test_classifier_rejects_shorts_and_live(self, monkeypatch):
        channel = _channel()
        sub = _sub(channel, max_videos_per_poll=5)

        feed_entries = [
            FeedEntry("regular1", "ok", "https://youtube.com/watch?v=regular1", None),
            FeedEntry("short1", "ok", "https://youtube.com/shorts/short1", None),
            FeedEntry("live1", "ok", "https://youtube.com/watch?v=live1", None),
            FeedEntry("regular2", "ok", "https://youtube.com/watch?v=regular2", None),
        ]
        monkeypatch.setattr(
            poll_module, "fetch_channel_feed",
            AsyncMock(return_value=feed_entries),
        )

        def fake_classify(url):
            from app.services.video_classifier import ClassificationResult
            if "/shorts/" in url:
                return ClassificationResult(False, "url contains /shorts/")
            if "live1" in url:
                return ClassificationResult(False, "live_status=is_live")
            return ClassificationResult(True, None)

        monkeypatch.setattr(
            "app.services.video_classifier.classify_video_url", fake_classify
        )

        submitted = []

        async def fake_submit(url, api_key=None):
            submitted.append(url)
            return {"job_id": str(uuid.uuid4()), "video_id": str(uuid.uuid4())}

        monkeypatch.setattr(poll_module, "_submit_video", fake_submit)
        monkeypatch.setattr(poll_module, "_tag_job_as_auto_ingest", AsyncMock())

        db = _DbStub()
        out = await poll_module._process_one_subscription(db, sub, budget_remaining=10.0)
        assert out["ingested"] == 2  # only the two regulars
        assert out["rejected_by_filter"] == 2
        # Submitted URLs should not include shorts or live
        assert len(submitted) == 2
        assert all("shorts" not in u and "live1" not in u for u in submitted)

    @pytest.mark.asyncio
    async def test_soft_cap_annotates_but_does_not_halt(self, monkeypatch):
        """Budget below threshold in per-sub handler still skips the sub — it's
        the outer loop that's soft. The inner skip is preserved as a safety
        valve for future hard-cap modes."""
        channel = _channel()
        sub = _sub(channel)

        entries = [FeedEntry("new1", "t1", "u1", None)]
        monkeypatch.setattr(
            poll_module, "fetch_channel_feed", AsyncMock(return_value=entries)
        )

        submitted = []

        async def fake_submit(url, api_key=None):
            submitted.append(url)
            return {"job_id": "j", "video_id": "v"}

        monkeypatch.setattr(poll_module, "_submit_video", fake_submit)

        db = _DbStub()
        out = await poll_module._process_one_subscription(db, sub, budget_remaining=0.01)
        assert out["skipped_reason"] == "auto_ingest_budget_exhausted"
        assert out["ingested"] == 0
        assert submitted == []

    @pytest.mark.asyncio
    async def test_rss_failure_increments_counter(self, monkeypatch):
        from app.services.subscriptions import SubscriptionError

        channel = _channel()
        sub = _sub(channel)

        monkeypatch.setattr(
            poll_module, "fetch_channel_feed",
            AsyncMock(side_effect=SubscriptionError("rss 500")),
        )

        db = _DbStub()
        out = await poll_module._process_one_subscription(db, sub, budget_remaining=10.0)
        assert "rss_error" in (out["skipped_reason"] or "")
        assert sub.consecutive_failure_count == 1

    @pytest.mark.asyncio
    async def test_disables_after_repeat_failures(self, monkeypatch):
        from app.services.subscriptions import SubscriptionError

        channel = _channel()
        sub = _sub(channel, consecutive_failure_count=2)

        monkeypatch.setattr(
            poll_module, "fetch_channel_feed",
            AsyncMock(side_effect=SubscriptionError("still broken")),
        )

        db = _DbStub()
        await poll_module._process_one_subscription(db, sub, budget_remaining=10.0)
        assert sub.enabled is False
        assert "Auto-disabled" in (sub.disabled_reason or "")


class TestCostTracker:
    def test_source_for_attempt_reason(self):
        from app.services.cost_tracker import source_for_attempt_reason

        assert source_for_attempt_reason("auto_ingest") == "auto_ingest"
        assert source_for_attempt_reason("operator_action") is None
        assert source_for_attempt_reason(None) is None

    def test_auto_ingest_budget_helper_returns_non_negative(self, monkeypatch):
        from app.services import cost_tracker

        monkeypatch.setattr(cost_tracker, "get_today_cost_by_source", lambda s: 3.50)
        monkeypatch.setattr(cost_tracker.settings, "auto_ingest_daily_cost_cap_usd", 4.0)
        assert cost_tracker.auto_ingest_budget_remaining() == pytest.approx(0.50)

        monkeypatch.setattr(cost_tracker, "get_today_cost_by_source", lambda s: 10.0)
        assert cost_tracker.auto_ingest_budget_remaining() == 0.0
