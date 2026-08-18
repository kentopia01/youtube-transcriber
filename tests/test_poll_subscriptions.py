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
        last_error=None,
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


class _LaneDbStub(_DbStub):
    def __init__(self, execute_values, *, get_value=None):
        super().__init__()
        self.execute_values = list(execute_values)
        self.get_value = get_value
        self.added = []

    async def execute(self, statement):
        value = self.execute_values.pop(0)
        result = MagicMock()
        result.scalar_one_or_none.return_value = value
        return result

    async def get(self, model, key):
        return self.get_value

    def add(self, value):
        self.added.append(value)


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
        # The 3 cap-truncated entries MUST NOT be marked as seen — they need
        # to surface on the next poll so we eventually drain the backlog.
        assert set(sub.last_seen_video_ids) == {"new0", "new1"}
        for cap_truncated in ("new2", "new3", "new4"):
            assert cap_truncated not in sub.last_seen_video_ids

    @pytest.mark.asyncio
    async def test_poll_wide_submission_limit_bounds_one_subscription(self, monkeypatch):
        channel = _channel()
        sub = _sub(channel, max_videos_per_poll=5)
        entries = [
            FeedEntry(f"bounded{i}", f"title {i}", f"https://youtube.test/{i}", None)
            for i in range(5)
        ]
        monkeypatch.setattr(poll_module, "fetch_channel_feed", AsyncMock(return_value=entries))
        monkeypatch.setattr(
            "app.services.video_classifier.classify_video_url",
            lambda url: __import__(
                "app.services.video_classifier", fromlist=["ClassificationResult"]
            ).ClassificationResult(True, None),
        )
        submit = AsyncMock(
            return_value={"job_id": str(uuid.uuid4()), "video_id": str(uuid.uuid4())}
        )
        monkeypatch.setattr(poll_module, "_submit_video", submit)
        monkeypatch.setattr(poll_module, "_tag_job_as_auto_ingest", AsyncMock())

        result = await poll_module._process_one_subscription(
            _DbStub(), sub, budget_remaining=10.0, submission_limit=2
        )

        assert result["ingested"] == 2
        assert submit.await_count == 2
        assert set(sub.last_seen_video_ids) == {"bounded0", "bounded1"}

    @pytest.mark.asyncio
    async def test_open_download_circuit_defers_poll_without_database_access(self, monkeypatch):
        from app.services.download_circuit import DownloadCircuitState

        monkeypatch.setattr(
            poll_module,
            "get_download_circuit_state",
            lambda: DownloadCircuitState(
                open=True,
                retry_after_seconds=900,
                failure_count=2,
                reason="clustered_youtube_access_degradation",
            ),
        )
        create_engine = MagicMock(side_effect=AssertionError("database should not be opened"))
        monkeypatch.setattr(poll_module, "create_async_engine", create_engine)

        result = await poll_module._run_poll()

        assert result["skipped_reason"] == "download_circuit_open"
        assert result["processed_subscriptions"] == 0
        create_engine.assert_not_called()

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
    async def test_upcoming_video_is_deferred_without_blocking_or_marking_seen(self, monkeypatch):
        channel = _channel()
        sub = _sub(channel, max_videos_per_poll=3, consecutive_failure_count=2)
        entries = [
            FeedEntry("upcoming001", "Soon", "https://youtube.test/upcoming", None),
            FeedEntry("regular0001", "Ready", "https://youtube.test/ready", None),
        ]
        monkeypatch.setattr(poll_module, "fetch_channel_feed", AsyncMock(return_value=entries))

        from app.services.video_classifier import ClassificationResult

        monkeypatch.setattr(
            "app.services.video_classifier.classify_video_url",
            lambda url: ClassificationResult(False, "upcoming", retry_later=True)
            if "upcoming" in url
            else ClassificationResult(True, None),
        )
        monkeypatch.setattr(
            poll_module,
            "_submit_video",
            AsyncMock(return_value={"job_id": str(uuid.uuid4()), "video_id": str(uuid.uuid4())}),
        )
        monkeypatch.setattr(poll_module, "_tag_job_as_auto_ingest", AsyncMock())

        result = await poll_module._process_one_subscription(
            _DbStub(), sub, budget_remaining=10.0
        )

        assert result["ingested"] == 1
        assert result["deferred_for_retry"] == 1
        assert "upcoming001" not in sub.last_seen_video_ids
        assert "regular0001" in sub.last_seen_video_ids
        assert sub.consecutive_failure_count == 0
        assert sub.last_error is None

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
        assert sub.last_error == "rss 500"

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


class TestLaneSharedProcessingAttach:
    def _lane_sub(self):
        return SimpleNamespace(
            id=uuid.uuid4(),
            lane_id=uuid.uuid4(),
        )

    @pytest.mark.asyncio
    async def test_completed_global_video_attaches_without_submit(self, monkeypatch):
        video = SimpleNamespace(id=uuid.uuid4(), status="completed")
        db = _LaneDbStub([None, video, None])
        submit = AsyncMock()
        monkeypatch.setattr(poll_module, "_submit_video", submit)

        disposition = await poll_module._attach_or_submit_lane_entry(
            db,
            self._lane_sub(),
            FeedEntry("completed01", "title", "url", None),
        )

        assert disposition == "attached_existing"
        submit.assert_not_awaited()
        assert len(db.added) == 1
        assert db.added[0].video_id == video.id

    @pytest.mark.asyncio
    async def test_active_global_video_attaches_to_existing_job(self, monkeypatch):
        video = SimpleNamespace(id=uuid.uuid4(), status="processing")
        job = SimpleNamespace(id=uuid.uuid4(), status="running")
        db = _LaneDbStub([None, video, job])
        submit = AsyncMock()
        monkeypatch.setattr(poll_module, "_submit_video", submit)

        disposition = await poll_module._attach_or_submit_lane_entry(
            db,
            self._lane_sub(),
            FeedEntry("active00001", "title", "url", None),
        )

        assert disposition == "attached_existing"
        submit.assert_not_awaited()
        assert db.added[0].processing_job_id == job.id

    @pytest.mark.asyncio
    async def test_new_video_submits_once_and_records_lane_item(self, monkeypatch):
        video = SimpleNamespace(id=uuid.uuid4(), status="processing")
        job_id = uuid.uuid4()
        db = _LaneDbStub([None, None], get_value=video)
        submit = AsyncMock(
            return_value={"video_id": str(video.id), "job_id": str(job_id)}
        )
        tag = AsyncMock()
        monkeypatch.setattr(poll_module, "_submit_video", submit)
        monkeypatch.setattr(poll_module, "_tag_job_as_auto_ingest", tag)

        disposition = await poll_module._attach_or_submit_lane_entry(
            db,
            self._lane_sub(),
            FeedEntry("newvideo001", "title", "https://youtube.test/new", None),
        )

        assert disposition == "submitted"
        submit.assert_awaited_once_with("https://youtube.test/new")
        tag.assert_awaited_once_with(db, str(job_id))
        assert db.added[0].processing_job_id == job_id

    @pytest.mark.asyncio
    async def test_existing_lane_item_is_idempotent(self, monkeypatch):
        db = _LaneDbStub([SimpleNamespace(id=uuid.uuid4())])
        submit = AsyncMock()
        monkeypatch.setattr(poll_module, "_submit_video", submit)

        disposition = await poll_module._attach_or_submit_lane_entry(
            db,
            self._lane_sub(),
            FeedEntry("already00001", "title", "url", None),
        )

        assert disposition == "already_attached"
        submit.assert_not_awaited()
        assert db.added == []


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
