"""Tests for the subscription service — RSS parsing, diff, poll state."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import subscriptions as subs_svc
from app.services.subscriptions import (
    FeedEntry,
    SubscriptionError,
    diff_new_videos,
    is_due_for_poll,
    mark_poll_failure,
    mark_poll_success,
    parse_feed,
    reset_daily_counter_if_needed,
)


# ---------------------------------------------------------------------------
# RSS parsing
# ---------------------------------------------------------------------------


SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <yt:videoId>abc12345678</yt:videoId>
    <title>First upload</title>
    <link href="https://www.youtube.com/watch?v=abc12345678"/>
    <published>2026-04-18T12:00:00+00:00</published>
  </entry>
  <entry>
    <yt:videoId>xyz98765432</yt:videoId>
    <title>Second upload</title>
    <link href="https://www.youtube.com/watch?v=xyz98765432"/>
    <published>2026-04-17T09:00:00+00:00</published>
  </entry>
</feed>
"""


class TestParseFeed:
    def test_extracts_entries_in_order(self):
        entries = parse_feed(SAMPLE_FEED)
        assert len(entries) == 2
        assert entries[0].video_id == "abc12345678"
        assert entries[0].title == "First upload"
        assert entries[0].url.endswith("v=abc12345678")
        assert entries[0].published_at is not None
        assert entries[1].video_id == "xyz98765432"

    def test_malformed_xml_raises(self):
        with pytest.raises(SubscriptionError):
            parse_feed("<not xml")

    def test_skips_entries_without_video_id(self):
        xml = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <entry>
    <title>No id</title>
  </entry>
</feed>"""
        entries = parse_feed(xml)
        assert entries == []


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


class TestDiff:
    def _entry(self, vid: str) -> FeedEntry:
        return FeedEntry(video_id=vid, title=vid, url=f"u/{vid}", published_at=None)

    def test_all_new(self):
        new = diff_new_videos([self._entry("a"), self._entry("b")], seen_ids=[])
        assert [e.video_id for e in new] == ["a", "b"]

    def test_drops_seen(self):
        new = diff_new_videos(
            [self._entry("a"), self._entry("b"), self._entry("c")],
            seen_ids=["b"],
        )
        assert [e.video_id for e in new] == ["a", "c"]

    def test_all_seen(self):
        assert diff_new_videos([self._entry("a")], seen_ids=["a"]) == []


# ---------------------------------------------------------------------------
# Poll state helpers
# ---------------------------------------------------------------------------


def _sub(**kw):
    defaults = dict(
        enabled=True,
        poll_frequency_hours=24,
        last_polled_at=None,
        last_seen_video_ids=[],
        videos_ingested_today=0,
        daily_counter_reset_at=None,
        consecutive_failure_count=0,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


class TestIsDue:
    def test_disabled_never_due(self):
        assert not is_due_for_poll(_sub(enabled=False))

    def test_never_polled_is_due(self):
        assert is_due_for_poll(_sub())

    def test_within_window_not_due(self):
        sub = _sub(last_polled_at=datetime.now(UTC) - timedelta(hours=12))
        assert not is_due_for_poll(sub)

    def test_beyond_window_due(self):
        sub = _sub(last_polled_at=datetime.now(UTC) - timedelta(hours=25))
        assert is_due_for_poll(sub)


class TestDailyCounterReset:
    def test_resets_on_new_day(self):
        yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
        sub = _sub(videos_ingested_today=7, daily_counter_reset_at=yesterday)
        reset_daily_counter_if_needed(sub)
        assert sub.videos_ingested_today == 0
        assert sub.daily_counter_reset_at == datetime.now(UTC).date()

    def test_same_day_keeps_counter(self):
        today = datetime.now(UTC).date()
        sub = _sub(videos_ingested_today=3, daily_counter_reset_at=today)
        reset_daily_counter_if_needed(sub)
        assert sub.videos_ingested_today == 3


class TestMarkPoll:
    def test_success_trims_seen_ids_to_50(self):
        sub = _sub(last_seen_video_ids=[f"old-{i}" for i in range(60)])
        mark_poll_success(sub, new_ids=["new-1", "new-2"])
        assert len(sub.last_seen_video_ids) == 50
        assert sub.last_seen_video_ids[0] == "new-1"
        assert sub.consecutive_failure_count == 0

    def test_failure_increments(self):
        sub = _sub()
        mark_poll_failure(sub, reason="rss 500")
        assert sub.consecutive_failure_count == 1
        assert sub.enabled is True

    def test_failure_disables_after_threshold(self):
        sub = _sub(consecutive_failure_count=2)
        mark_poll_failure(sub, reason="rss 500", disable_after=3)
        assert sub.consecutive_failure_count == 3
        assert sub.enabled is False
        assert "Auto-disabled" in (sub.disabled_reason or "")


# ---------------------------------------------------------------------------
# Resolve channel by name
# ---------------------------------------------------------------------------


class _FakeScalars:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return list(self._items)


class _FakeDb:
    def __init__(self, channels):
        self._channels = channels

    async def execute(self, stmt):
        return _FakeScalars(self._channels)


class TestResolveChannel:
    @pytest.mark.asyncio
    async def test_exact_match_wins(self):
        channels = [
            SimpleNamespace(id=uuid.UUID(int=1), name="All-In Podcast"),
            SimpleNamespace(id=uuid.UUID(int=2), name="All-In Side Cast"),
        ]
        match = await subs_svc.resolve_channel_by_query(_FakeDb(channels), "All-In Podcast")
        assert match.id == channels[0].id

    @pytest.mark.asyncio
    async def test_substring_fallback(self):
        channels = [SimpleNamespace(id=uuid.UUID(int=3), name="My Second Channel")]
        match = await subs_svc.resolve_channel_by_query(_FakeDb(channels), "second")
        assert match.id == channels[0].id

    @pytest.mark.asyncio
    async def test_empty_query_returns_none(self):
        match = await subs_svc.resolve_channel_by_query(_FakeDb([]), "")
        assert match is None
