"""Tests for the regular-video classifier."""

from __future__ import annotations

import pytest

from app.services.video_classifier import (
    ClassificationResult,
    classify_video_info,
    classify_video_url,
)


class TestClassifyVideoInfo:
    def test_regular_video_accepted(self):
        info = {
            "duration": 1800,  # 30 min podcast
            "webpage_url": "https://www.youtube.com/watch?v=abc",
            "is_live": False,
            "live_status": "not_live",
        }
        r = classify_video_info(info)
        assert r.is_regular is True
        assert r.reason is None

    def test_short_by_duration_rejected(self):
        info = {
            "duration": 45,
            "webpage_url": "https://www.youtube.com/watch?v=abc",
            "is_live": False,
            "live_status": "not_live",
        }
        r = classify_video_info(info)
        assert r.is_regular is False
        assert "Short" in r.reason

    def test_short_by_url_rejected(self):
        info = {
            "duration": 50,
            "webpage_url": "https://www.youtube.com/shorts/xyz",
            "is_live": False,
            "live_status": "not_live",
        }
        r = classify_video_info(info)
        assert r.is_regular is False
        assert "/shorts/" in r.reason

    def test_live_stream_rejected(self):
        info = {
            "duration": 3600,
            "webpage_url": "https://www.youtube.com/watch?v=livevid",
            "is_live": True,
            "live_status": "is_live",
        }
        r = classify_video_info(info)
        assert r.is_regular is False
        assert "live" in r.reason

    def test_upcoming_stream_rejected(self):
        info = {
            "duration": None,
            "webpage_url": "https://www.youtube.com/watch?v=upcoming",
            "is_live": False,
            "live_status": "is_upcoming",
        }
        r = classify_video_info(info)
        assert r.is_regular is False
        assert "is_upcoming" in r.reason

    def test_past_live_stream_accepted(self):
        """Past live streams (recordings) are still worth ingesting."""
        info = {
            "duration": 7200,
            "webpage_url": "https://www.youtube.com/watch?v=replay",
            "is_live": False,
            "live_status": "was_live",
        }
        r = classify_video_info(info)
        assert r.is_regular is True

    def test_exactly_60s_treated_as_short(self):
        info = {
            "duration": 60,
            "webpage_url": "https://www.youtube.com/watch?v=borderline",
            "is_live": False,
            "live_status": "not_live",
        }
        r = classify_video_info(info)
        assert r.is_regular is False

    def test_61s_treated_as_regular(self):
        info = {
            "duration": 61,
            "webpage_url": "https://www.youtube.com/watch?v=borderline",
            "is_live": False,
            "live_status": "not_live",
        }
        r = classify_video_info(info)
        assert r.is_regular is True

    def test_unknown_duration_accepted(self):
        info = {
            "duration": None,
            "webpage_url": "https://www.youtube.com/watch?v=unknown",
            "is_live": False,
            "live_status": "not_live",
        }
        r = classify_video_info(info)
        assert r.is_regular is True

    def test_bool_coercion(self):
        regular = ClassificationResult(True, None)
        rejected = ClassificationResult(False, "nope")
        assert bool(regular) is True
        assert bool(rejected) is False


class TestClassifyVideoUrl:
    def test_fails_open_on_lookup_error(self, monkeypatch):
        def boom(url):
            raise RuntimeError("yt-dlp exploded")

        monkeypatch.setattr("app.services.youtube.get_video_info", boom)
        r = classify_video_url("https://www.youtube.com/watch?v=x")
        # Fail-open: don't drop a legit video because of a transient lookup issue
        assert r.is_regular is True

    def test_uses_classifier_when_lookup_succeeds(self, monkeypatch):
        fake_info = {
            "duration": 20,
            "webpage_url": "https://www.youtube.com/shorts/s",
            "live_status": "not_live",
            "is_live": False,
        }
        monkeypatch.setattr(
            "app.services.youtube.get_video_info", lambda url: fake_info
        )
        r = classify_video_url("https://www.youtube.com/shorts/s")
        assert r.is_regular is False
