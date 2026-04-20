"""Tests for the daily persona-refresh sweep + narrowed channel_needs_persona."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.tasks import refresh_stale_personas as mod


def _persona(scope_id, generated_at, display_name="Ep"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        scope_type="channel",
        scope_id=scope_id,
        display_name=display_name,
        generated_at=generated_at,
    )


class _FakeExec:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value

    def scalars(self):
        class _S:
            def __init__(self, items):
                self._items = items

            def all(inner):
                return list(inner._items)

        return _S(self._value if isinstance(self._value, list) else [])


class _FakeSession:
    """Queued responses in order. Each `execute()` pops the next value."""

    def __init__(self, responses):
        self._q = list(responses)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, stmt, *a, **kw):
        if not self._q:
            return _FakeExec([])
        return _FakeExec(self._q.pop(0))


class TestRunRefreshSweep:
    def test_queues_only_channels_with_new_completions(self, monkeypatch):
        cid_active = str(uuid.UUID(int=1))
        cid_quiet = str(uuid.UUID(int=2))
        gen_at = datetime.now(UTC) - timedelta(days=3)

        personas = [
            _persona(cid_active, gen_at, "Active"),
            _persona(cid_quiet, gen_at, "Quiet"),
        ]
        # responses: first = personas list; then one scalar per persona
        responses = [personas, 4, 0]

        enqueued = []
        monkeypatch.setattr(
            mod, "enqueue_channel_persona",
            lambda channel_id, forced: enqueued.append((channel_id, forced)),
        )
        monkeypatch.setattr(
            mod, "create_engine",
            lambda *a, **kw: MagicMock(dispose=lambda: None),
        )
        monkeypatch.setattr(mod, "Session", lambda engine: _FakeSession(responses))

        result = mod.run_refresh_sweep()
        assert result["queued"] == 1
        assert result["skipped"] == 1
        assert enqueued == [(cid_active, True)]

    def test_skips_persona_with_bad_scope_id(self, monkeypatch):
        bad = _persona("not-a-uuid", datetime.now(UTC), "Broken")
        # responses: only the personas list
        responses = [[bad]]

        enqueued = []
        monkeypatch.setattr(
            mod, "enqueue_channel_persona",
            lambda channel_id, forced: enqueued.append((channel_id, forced)),
        )
        monkeypatch.setattr(
            mod, "create_engine",
            lambda *a, **kw: MagicMock(dispose=lambda: None),
        )
        monkeypatch.setattr(mod, "Session", lambda engine: _FakeSession(responses))

        result = mod.run_refresh_sweep()
        assert result["queued"] == 0
        assert enqueued == []


class TestChannelNeedsPersonaNarrowed:
    """channel_needs_persona now only answers first-generation."""

    @pytest.mark.asyncio
    async def test_first_gen_when_over_threshold_and_no_persona(self, monkeypatch):
        from app.services import persona as ps

        monkeypatch.setattr(ps, "count_completed_videos", _async_return(5))
        monkeypatch.setattr(ps, "get_persona", _async_return(None))
        should, reason = await ps.channel_needs_persona(
            db=None, channel_id=uuid.uuid4()
        )
        assert should is True
        assert "no persona yet" in reason

    @pytest.mark.asyncio
    async def test_declines_even_when_many_new_videos_if_persona_exists(self, monkeypatch):
        """Refresh is the sweep's job; embed-hook no longer triggers it."""
        from app.services import persona as ps

        existing = SimpleNamespace(
            id=uuid.uuid4(),
            videos_at_generation=1,
            refresh_after_videos=5,
        )
        monkeypatch.setattr(ps, "count_completed_videos", _async_return(100))
        monkeypatch.setattr(ps, "get_persona", _async_return(existing))
        should, reason = await ps.channel_needs_persona(
            db=None, channel_id=uuid.uuid4()
        )
        assert should is False
        assert "refreshes handled by daily sweep" in reason

    @pytest.mark.asyncio
    async def test_under_min_videos_still_declines(self, monkeypatch):
        from app.services import persona as ps

        monkeypatch.setattr(ps, "count_completed_videos", _async_return(2))
        monkeypatch.setattr(ps, "get_persona", _async_return(None))
        should, reason = await ps.channel_needs_persona(
            db=None, channel_id=uuid.uuid4()
        )
        assert should is False
        assert "2/3" in reason


def _async_return(value):
    async def _impl(*a, **kw):
        return value

    return _impl
