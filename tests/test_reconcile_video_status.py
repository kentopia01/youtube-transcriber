"""Tests for the video-status reconciler."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.tasks import reconcile_video_status as mod


class _FakeExecResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _FakeSession:
    """In-order execute() responses. First call is the SELECT (returns rows);
    subsequent calls are UPDATEs (captured as side-effects)."""

    def __init__(self, rows):
        self._rows = rows
        self.updates: list[dict] = []
        self.committed = False
        self._call = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, stmt, params=None):
        self._call += 1
        if self._call == 1:
            return _FakeExecResult(self._rows)
        self.updates.append(params or {})
        return _FakeExecResult([])

    def commit(self):
        self.committed = True


def _row(status="transcribed", stale=True):
    return SimpleNamespace(
        id=uuid.uuid4(),
        title=f"Stuck video ({status})",
        status=status,
        updated_at=datetime.now(UTC) - timedelta(hours=5) if stale else datetime.now(UTC),
    )


class TestFindAndReconcile:
    def test_updates_each_stuck_row(self, monkeypatch):
        rows = [_row("transcribed"), _row("downloaded"), _row("summarized")]
        fake = _FakeSession(rows)

        result = mod._find_and_reconcile(fake, quiet_for_minutes=30)
        assert len(result) == 3
        assert len(fake.updates) == 3
        assert fake.committed is True
        assert all(u["reason"].startswith("Reconciled:") for u in fake.updates)

    def test_no_candidates_returns_empty(self):
        fake = _FakeSession([])
        result = mod._find_and_reconcile(fake, quiet_for_minutes=30)
        assert result == []
        assert fake.updates == []
        assert fake.committed is True


class TestReconcileOnce:
    def test_returns_stats_dict(self, monkeypatch):
        # End-to-end: mock out create_engine + Session
        monkeypatch.setattr(
            mod, "create_engine", lambda *a, **kw: MagicMock(dispose=lambda: None)
        )
        monkeypatch.setattr(mod, "Session", lambda engine: _FakeSession([]))

        result = mod.reconcile_once(quiet_for_minutes=5)
        assert result["reconciled"] == 0
        assert result["quiet_for_minutes"] == 5
        assert result["rows"] == []

    def test_uses_settings_default_when_unset(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "pipeline_stale_timeout_queued_minutes", 240)
        monkeypatch.setattr(
            mod, "create_engine", lambda *a, **kw: MagicMock(dispose=lambda: None)
        )
        monkeypatch.setattr(mod, "Session", lambda engine: _FakeSession([]))

        result = mod.reconcile_once()
        assert result["quiet_for_minutes"] == 240
