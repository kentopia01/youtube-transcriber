"""Tests for dismiss/undismiss endpoints + retry auto-un-dismiss + /dismiss command."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_db
from app.main import create_app


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        class _S:
            def __init__(self, v):
                self._v = v

            def all(inner):
                return inner._v if isinstance(inner._v, list) else [inner._v] if inner._v else []

        return _S(self._value)


class _StubSession:
    def __init__(self, video=None, videos=None):
        self._video = video
        self._videos = videos or []
        self.committed = False

    async def execute(self, stmt, *a, **kw):
        # If caller wants a list (e.g. scalars().all()), use self._videos; else video.
        return _FakeResult(self._videos if self._videos else self._video)

    async def commit(self):
        self.committed = True


def _client(stub):
    app = create_app()

    async def _override():
        yield stub

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def _fake_video(title="Test", status="failed", dismissed=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        title=title,
        status=status,
        error_message=None,
        dismissed_at=dismissed,
        dismissed_reason=None,
    )


# ---------------------------------------------------------------------------
# Dismiss / undismiss endpoints
# ---------------------------------------------------------------------------


class TestDismissEndpoint:
    def test_404_when_missing(self):
        stub = _StubSession(video=None)
        client = _client(stub)
        resp = client.post(f"/api/videos/{uuid.uuid4()}/dismiss")
        assert resp.status_code == 404

    def test_marks_dismissed_at(self):
        video = _fake_video()
        stub = _StubSession(video=video)
        client = _client(stub)

        resp = client.post(
            f"/api/videos/{video.id}/dismiss", json={"reason": "not interesting"}
        )
        assert resp.status_code == 200
        assert video.dismissed_at is not None
        assert video.dismissed_reason == "not interesting"
        assert stub.committed


class TestUndismissEndpoint:
    def test_clears_dismissal(self):
        video = _fake_video(dismissed=datetime.now(UTC))
        video.dismissed_reason = "old reason"
        stub = _StubSession(video=video)
        client = _client(stub)

        resp = client.post(f"/api/videos/{video.id}/undismiss")
        assert resp.status_code == 200
        assert video.dismissed_at is None
        assert video.dismissed_reason is None


# ---------------------------------------------------------------------------
# /dismiss Telegram command
# ---------------------------------------------------------------------------


telegram = pytest.importorskip("telegram")

from app import telegram_bot  # noqa: E402


@pytest.fixture
def _allow_user(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "telegram_allowed_users", [1])


def _update_stub(args=None):
    reply = AsyncMock()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1),
        effective_chat=SimpleNamespace(id=42),
        message=SimpleNamespace(reply_text=reply),
    )
    context = SimpleNamespace(args=args or [])
    return update, context, reply


class TestDismissTelegramCommand:
    @pytest.mark.asyncio
    async def test_usage_when_no_args(self, _allow_user):
        update, context, reply = _update_stub()
        await telegram_bot.dismiss_command(update, context)
        assert "Usage" in reply.call_args.args[0]

    @pytest.mark.asyncio
    async def test_no_match(self, _allow_user, monkeypatch):
        stub = _StubSession(videos=[])
        stub.close = AsyncMock()
        monkeypatch.setattr(
            telegram_bot, "_get_db", AsyncMock(return_value=stub)
        )
        update, context, reply = _update_stub(args=["unknown"])
        await telegram_bot.dismiss_command(update, context)
        assert "No failed" in reply.call_args.args[0]

    @pytest.mark.asyncio
    async def test_bulk_dismisses_matches(self, _allow_user, monkeypatch):
        v1 = _fake_video(title="Old Episode About X")
        v2 = _fake_video(title="Another Episode About X")
        stub_session = _StubSession(videos=[v1, v2])
        # Add async close to the stub so the handler's `finally: await db.close()` works.
        stub_session.close = AsyncMock()
        monkeypatch.setattr(
            telegram_bot, "_get_db", AsyncMock(return_value=stub_session)
        )
        update, context, reply = _update_stub(args=["episode"])
        await telegram_bot.dismiss_command(update, context)
        assert v1.dismissed_at is not None
        assert v2.dismissed_at is not None
        assert "Dismissed 2 failed video(s)" in reply.call_args.args[0]
