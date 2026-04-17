"""Tests for inline-button callback dispatcher (Phase C)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

telegram = pytest.importorskip("telegram")

from app import telegram_bot  # noqa: E402


@pytest.fixture(autouse=True)
def _allow_single_user(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "telegram_allowed_users", [1])


def _query_stub(data, allowed=True):
    answer = AsyncMock()
    reply = AsyncMock()
    msg = SimpleNamespace(reply_text=reply)
    q = SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=1 if allowed else 999),
        message=msg,
        answer=answer,
    )
    update = SimpleNamespace(callback_query=q)
    context = SimpleNamespace(args=[])
    return update, context, q, reply, answer


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_rejects_unauthorized(self):
        update, context, q, reply, answer = _query_stub("video:open:v1", allowed=False)
        await telegram_bot.callback_dispatcher(update, context)
        answer.assert_awaited_once()
        # show_alert=True was passed so the user sees "Unauthorized"
        assert "Unauthorized" in answer.call_args.args[0]

    @pytest.mark.asyncio
    async def test_invalid_data_format(self):
        update, context, q, reply, answer = _query_stub("garbage")
        await telegram_bot.callback_dispatcher(update, context)
        answer.assert_awaited()

    @pytest.mark.asyncio
    async def test_unknown_action_surfaces(self):
        update, context, q, reply, answer = _query_stub("pizza:cheese:extra")
        await telegram_bot.callback_dispatcher(update, context)
        reply.assert_awaited()
        assert "Unknown" in reply.call_args.args[0]

    @pytest.mark.asyncio
    async def test_video_open_dispatches(self, monkeypatch):
        called = {}

        async def fake_video_open(query, vid):
            called["vid"] = vid

        monkeypatch.setattr(telegram_bot, "_cb_video_open", fake_video_open)
        update, context, *_ = _query_stub("video:open:v-123")
        await telegram_bot.callback_dispatcher(update, context)
        assert called["vid"] == "v-123"

    @pytest.mark.asyncio
    async def test_job_retry_dispatches(self, monkeypatch):
        called = {}

        async def fake_retry(query, jid):
            called["jid"] = jid

        monkeypatch.setattr(telegram_bot, "_cb_job_retry", fake_retry)
        update, context, *_ = _query_stub("job:retry:j-42")
        await telegram_bot.callback_dispatcher(update, context)
        assert called["jid"] == "j-42"

    @pytest.mark.asyncio
    async def test_persona_refresh_enqueues(self, monkeypatch):
        enqueue_mock = MagicMock()
        monkeypatch.setattr(
            "app.tasks.generate_persona.enqueue_channel_persona",
            enqueue_mock,
        )
        update, context, q, reply, _ = _query_stub("persona:refresh:c-1")
        await telegram_bot.callback_dispatcher(update, context)
        enqueue_mock.assert_called_once_with("c-1", forced=True)
        reply.assert_awaited()
        assert "rebuild" in reply.call_args.args[0]


class TestJobRetryHttp:
    @pytest.mark.asyncio
    async def test_success_reply(self, monkeypatch):
        import httpx

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"status": "queued"}

        class FakeClient:
            def __init__(self, *a, **kw):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def post(self, *a, **kw):
                return fake_resp

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

        reply = AsyncMock()
        q = SimpleNamespace(message=SimpleNamespace(reply_text=reply))
        await telegram_bot._cb_job_retry(q, "j-999")

        reply.assert_awaited_once()
        assert "Retry queued" in reply.call_args.args[0]

    @pytest.mark.asyncio
    async def test_failure_surfaces(self, monkeypatch):
        import httpx

        fake_resp = MagicMock()
        fake_resp.status_code = 400
        fake_resp.json.return_value = {"detail": "already complete"}

        class FakeClient:
            def __init__(self, *a, **kw):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def post(self, *a, **kw):
                return fake_resp

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

        reply = AsyncMock()
        q = SimpleNamespace(message=SimpleNamespace(reply_text=reply))
        await telegram_bot._cb_job_retry(q, "j-999")

        reply.assert_awaited_once()
        assert "already complete" in reply.call_args.args[0]
