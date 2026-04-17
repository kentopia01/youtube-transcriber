"""Tests for the /api/subscriptions endpoints + Telegram commands."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_db
from app.main import create_app


class _StubSession:
    def __init__(self, subs=None, channel=None):
        self._subs = subs or []
        self._channel = channel
        self._removed = []

    async def execute(self, stmt):
        class _R:
            def __init__(self, items):
                self._items = items

            def scalars(self):
                class _S:
                    def __init__(self, items):
                        self._items = items

                    def all(inner):
                        return list(inner._items)

                return _S(self._items)

        return _R(self._subs)

    async def get(self, model, key):
        from app.models.channel import Channel
        from app.models.channel_subscription import ChannelSubscription

        if model is Channel:
            return self._channel
        if model is ChannelSubscription:
            for s in self._subs:
                if s.id == key:
                    return s
            return None
        return None

    async def delete(self, obj):
        self._removed.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


def _client(stub):
    app = create_app()

    async def _override():
        yield stub

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


class TestListEndpoint:
    def test_empty(self):
        client = _client(_StubSession())
        r = client.get("/api/subscriptions")
        assert r.status_code == 200
        assert r.json() == {"subscriptions": []}

    def test_serializes_subscriptions(self):
        ch = SimpleNamespace(id=uuid.UUID(int=1), name="Lex")
        sub = SimpleNamespace(
            id=uuid.UUID(int=2),
            channel_id=ch.id,
            channel=ch,
            enabled=True,
            poll_frequency_hours=24,
            max_videos_per_poll=3,
            last_polled_at=datetime(2026, 4, 18, tzinfo=UTC),
            videos_ingested_today=1,
            consecutive_failure_count=0,
            disabled_reason=None,
        )
        client = _client(_StubSession(subs=[sub]))
        r = client.get("/api/subscriptions")
        body = r.json()
        assert len(body["subscriptions"]) == 1
        assert body["subscriptions"][0]["channel_name"] == "Lex"
        assert body["subscriptions"][0]["enabled"] is True


class TestCreateEndpoint:
    def test_rejects_non_channel_url(self):
        client = _client(_StubSession())
        r = client.post("/api/subscriptions", json={"url": "https://youtu.be/abc"})
        assert r.status_code == 400
        assert "channel" in r.json()["detail"].lower()

    def test_rejects_empty_url(self):
        client = _client(_StubSession())
        r = client.post("/api/subscriptions", json={"url": ""})
        assert r.status_code == 400


class TestPatchEndpoint:
    def test_404_when_missing(self):
        client = _client(_StubSession())
        r = client.patch(
            f"/api/subscriptions/{uuid.uuid4()}",
            json={"enabled": False},
        )
        assert r.status_code == 404

    def test_disables(self):
        sub = SimpleNamespace(
            id=uuid.UUID(int=9),
            channel_id=uuid.UUID(int=1),
            channel=SimpleNamespace(id=uuid.UUID(int=1), name="Lex"),
            enabled=True,
            poll_frequency_hours=24,
            max_videos_per_poll=3,
            last_polled_at=None,
            videos_ingested_today=0,
            consecutive_failure_count=0,
            disabled_reason=None,
        )
        stub = _StubSession(
            subs=[sub], channel=SimpleNamespace(id=uuid.UUID(int=1), name="Lex")
        )
        client = _client(stub)
        r = client.patch(f"/api/subscriptions/{sub.id}", json={"enabled": False})
        assert r.status_code == 200
        assert sub.enabled is False
        assert sub.disabled_reason == "user_disabled"


# ---------------------------------------------------------------------------
# Telegram commands
# ---------------------------------------------------------------------------


telegram = pytest.importorskip("telegram")

from app import telegram_bot  # noqa: E402


@pytest.fixture(autouse=True)
def _allow_single_user(monkeypatch):
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


class TestSubscribeCommand:
    @pytest.mark.asyncio
    async def test_usage_when_empty(self):
        update, context, reply = _update_stub()
        await telegram_bot.subscribe_command(update, context)
        assert "Usage" in reply.call_args.args[0]

    @pytest.mark.asyncio
    async def test_success_hits_api(self, monkeypatch):
        import httpx

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {
            "channel_name": "Lex", "poll_frequency_hours": 24, "max_videos_per_poll": 3,
        }

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

        update, context, reply = _update_stub(args=["https://youtube.com/@lex"])
        await telegram_bot.subscribe_command(update, context)
        reply.assert_awaited_once()
        assert "Subscribed" in reply.call_args.args[0]


class TestUnsubscribeCommand:
    @pytest.mark.asyncio
    async def test_usage_when_empty(self):
        update, context, reply = _update_stub()
        await telegram_bot.unsubscribe_command(update, context)
        assert "Usage" in reply.call_args.args[0]

    @pytest.mark.asyncio
    async def test_no_match(self, monkeypatch):
        monkeypatch.setattr(
            telegram_bot, "_get_db",
            AsyncMock(return_value=AsyncMock(close=AsyncMock())),
        )
        monkeypatch.setattr(
            "app.services.subscriptions.resolve_channel_by_query",
            AsyncMock(return_value=None),
        )
        update, context, reply = _update_stub(args=["nope"])
        await telegram_bot.unsubscribe_command(update, context)
        assert "No channel matches" in reply.call_args.args[0]


class TestSubscriptionsCommand:
    @pytest.mark.asyncio
    async def test_empty_list(self, monkeypatch):
        monkeypatch.setattr(
            telegram_bot, "_get_db",
            AsyncMock(return_value=AsyncMock(close=AsyncMock())),
        )
        monkeypatch.setattr(
            "app.services.subscriptions.list_subscriptions",
            AsyncMock(return_value=[]),
        )
        update, context, reply = _update_stub()
        await telegram_bot.subscriptions_command(update, context)
        assert "No subscriptions" in reply.call_args.args[0]

    @pytest.mark.asyncio
    async def test_lists_enabled_and_disabled(self, monkeypatch):
        channel = SimpleNamespace(id=uuid.uuid4(), name="All-In")
        sub_on = SimpleNamespace(
            id=uuid.uuid4(), channel=channel, channel_id=channel.id, enabled=True,
            poll_frequency_hours=24, max_videos_per_poll=3, last_polled_at=None,
            videos_ingested_today=0, consecutive_failure_count=0, disabled_reason=None,
        )
        sub_off = SimpleNamespace(
            id=uuid.uuid4(), channel=channel, channel_id=channel.id, enabled=False,
            poll_frequency_hours=24, max_videos_per_poll=3, last_polled_at=None,
            videos_ingested_today=0, consecutive_failure_count=0,
            disabled_reason="user_disabled",
        )
        monkeypatch.setattr(
            telegram_bot, "_get_db",
            AsyncMock(return_value=AsyncMock(close=AsyncMock())),
        )
        monkeypatch.setattr(
            "app.services.subscriptions.list_subscriptions",
            AsyncMock(return_value=[sub_on, sub_off]),
        )
        update, context, reply = _update_stub()
        await telegram_bot.subscriptions_command(update, context)
        body = reply.call_args.args[0]
        assert "1 active" in body
        assert "1 disabled" in body
