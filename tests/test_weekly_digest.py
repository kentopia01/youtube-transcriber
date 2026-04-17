"""Tests for the weekly digest Celery task."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class _FakeExec:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value

    def all(self):
        return self._value if isinstance(self._value, list) else []


class _FakeSession:
    """Sequential-response stub. Each execute() returns the next value."""

    def __init__(self, values):
        self._values = list(values)
        self._i = 0

    def execute(self, *a, **kw):
        v = self._values[self._i]
        self._i += 1
        return _FakeExec(v)


class TestBuildDigestText:
    def test_zero_activity_message(self):
        from app.tasks.weekly_digest import build_digest_text

        db = _FakeSession([0, 0, 0, 0, 0, 0.0, []])
        payload = build_digest_text(db)

        assert "Quiet week" in payload["text"]
        assert payload["stats"]["videos_ingested"] == 0
        assert payload["stats"]["cost_usd"] == 0.0

    def test_populated_digest(self):
        from app.tasks.weekly_digest import build_digest_text

        # order of execute() calls in build_digest_text:
        #   ingested, completed, failed_videos, failed_jobs, personas, cost, top_channels
        db = _FakeSession([
            12,
            10,
            2,
            3,
            1,
            1.23,
            [("All-In", 4), ("Predictive History", 2)],
        ])
        payload = build_digest_text(db)

        assert "12" in payload["text"]
        assert "10 completed" in payload["text"]
        assert "2 failed" in payload["text"]
        assert "$1.23" in payload["text"]
        assert "All-In" in payload["text"]
        assert payload["stats"]["personas_built"] == 1


class TestWeeklyTelegramDigestTask:
    def test_task_invokes_notifier(self, monkeypatch):
        from app.tasks import weekly_digest as mod

        fake_payload = {
            "text": "📊 Weekly digest ...",
            "window_start": "a",
            "window_end": "b",
            "stats": {"videos_ingested": 1},
        }

        # Bypass DB entirely
        monkeypatch.setattr(mod, "create_engine", lambda *a, **kw: MagicMock(dispose=lambda: None))
        monkeypatch.setattr(mod, "Session", lambda engine: _CtxStub())
        monkeypatch.setattr(mod, "build_digest_text", lambda db: fake_payload)

        sent = []
        monkeypatch.setattr(
            "app.services.telegram_notify.notify",
            lambda event, payload=None: sent.append((event, payload)),
        )

        result = mod.weekly_telegram_digest()

        assert ("digest.weekly", fake_payload) in sent
        assert result == fake_payload["stats"]


class _CtxStub:
    def __enter__(self):
        return MagicMock()

    def __exit__(self, *a):
        return False
