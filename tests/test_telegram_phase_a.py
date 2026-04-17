"""Tests for the Phase A feature-parity Telegram commands."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

telegram = pytest.importorskip("telegram")

from app import telegram_bot  # noqa: E402


def _update_stub(args=None):
    reply_mock = AsyncMock()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1),
        effective_chat=SimpleNamespace(id=42),
        message=SimpleNamespace(reply_text=reply_mock),
    )
    context = SimpleNamespace(args=args or [])
    return update, context, reply_mock


@pytest.fixture(autouse=True)
def _allow_single_user(monkeypatch):
    # Tests run with the single allowed user id = 1
    from app.config import settings
    monkeypatch.setattr(settings, "telegram_allowed_users", [1])
    yield


# ---------------------------------------------------------------------------
# Command manifest + /help
# ---------------------------------------------------------------------------


class TestCommandManifest:
    def test_manifest_has_19_commands(self):
        assert len(telegram_bot._build_command_manifest()) == 19

    def test_manifest_includes_new_commands(self):
        names = {c.name for c in telegram_bot._build_command_manifest()}
        for expected in ("submit", "queue", "search", "ask_video",
                         "refresh_persona", "cost", "notify", "help"):
            assert expected in names

    def test_names_are_unique(self):
        names = [c.name for c in telegram_bot._build_command_manifest()]
        assert len(names) == len(set(names))


class TestHelpCommand:
    @pytest.mark.asyncio
    async def test_help_lists_all_groups(self):
        update, context, reply = _update_stub()
        await telegram_bot.help_command(update, context)
        reply.assert_awaited_once()
        text = reply.call_args.args[0]
        for group in ("Getting started", "Content", "Chat", "Library", "Admin"):
            assert group in text
        # spot-check a few commands
        for cmd in ("/submit", "/queue", "/ask_video", "/notify"):
            assert cmd in text


# ---------------------------------------------------------------------------
# /submit
# ---------------------------------------------------------------------------


class TestSubmitCommand:
    @pytest.mark.asyncio
    async def test_usage_when_empty(self):
        update, context, reply = _update_stub(args=[])
        await telegram_bot.submit_command(update, context)
        reply.assert_awaited_once()
        assert "Usage" in reply.call_args.args[0]

    @pytest.mark.asyncio
    async def test_submits_video_url_to_api(self, monkeypatch):
        import httpx

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {
            "job_id": "j1", "video_id": "v1", "status": "queued",
        }

        captured = {}

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, path, json=None, headers=None):
                captured["path"] = path
                captured["body"] = json
                return fake_resp

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
        monkeypatch.setattr(
            "app.services.youtube.is_channel_url",
            lambda u: False,
        )

        update, context, reply = _update_stub(args=["https://youtu.be/abc"])
        await telegram_bot.submit_command(update, context)

        assert captured["path"] == "/api/videos"
        assert captured["body"]["url"] == "https://youtu.be/abc"
        reply.assert_awaited_once()
        assert "queued" in reply.call_args.args[0].lower()

    @pytest.mark.asyncio
    async def test_submits_channel_url_to_channels_api(self, monkeypatch):
        import httpx

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"channel_name": "Lex", "total_videos": 42}

        captured = {}

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, path, json=None, headers=None):
                captured["path"] = path
                return fake_resp

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
        monkeypatch.setattr(
            "app.services.youtube.is_channel_url",
            lambda u: True,
        )

        update, context, reply = _update_stub(args=["https://youtube.com/@lex"])
        await telegram_bot.submit_command(update, context)

        assert captured["path"] == "/api/channels"
        reply.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_surfaces_api_error(self, monkeypatch):
        import httpx

        fake_resp = MagicMock()
        fake_resp.status_code = 400
        fake_resp.json.return_value = {"detail": "bad URL"}

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
        monkeypatch.setattr(
            "app.services.youtube.is_channel_url",
            lambda u: False,
        )

        update, context, reply = _update_stub(args=["https://youtu.be/x"])
        await telegram_bot.submit_command(update, context)
        assert "bad URL" in reply.call_args.args[0]


# ---------------------------------------------------------------------------
# /refresh_persona
# ---------------------------------------------------------------------------


class TestRefreshPersonaCommand:
    @pytest.mark.asyncio
    async def test_usage_when_empty(self):
        update, context, reply = _update_stub(args=[])
        await telegram_bot.refresh_persona_command(update, context)
        assert "Usage" in reply.call_args.args[0]

    @pytest.mark.asyncio
    async def test_no_match(self, monkeypatch):
        monkeypatch.setattr(telegram_bot, "_get_db", AsyncMock(return_value=AsyncMock(close=AsyncMock())))
        monkeypatch.setattr(
            telegram_bot, "_resolve_channel_for_persona",
            AsyncMock(return_value=(None, None)),
        )
        update, context, reply = _update_stub(args=["unknown"])
        await telegram_bot.refresh_persona_command(update, context)
        assert "No channel persona matches" in reply.call_args.args[0]

    @pytest.mark.asyncio
    async def test_enqueues_rebuild(self, monkeypatch):
        ch = SimpleNamespace(id=uuid.UUID(int=5), name="Predictive History")
        p = SimpleNamespace(id=uuid.uuid4(), display_name="Predictive History")

        monkeypatch.setattr(telegram_bot, "_get_db", AsyncMock(return_value=AsyncMock(close=AsyncMock())))
        monkeypatch.setattr(
            telegram_bot, "_resolve_channel_for_persona",
            AsyncMock(return_value=(ch, p)),
        )
        enqueue_mock = MagicMock()
        monkeypatch.setattr(
            "app.tasks.generate_persona.enqueue_channel_persona", enqueue_mock
        )

        update, context, reply = _update_stub(args=["Predict"])
        await telegram_bot.refresh_persona_command(update, context)

        enqueue_mock.assert_called_once_with(str(ch.id), forced=True)
        assert "Queued persona rebuild" in reply.call_args.args[0]


# ---------------------------------------------------------------------------
# /notify
# ---------------------------------------------------------------------------


class TestNotifyCommand:
    @pytest.mark.asyncio
    async def test_status_default(self, tmp_path, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "telegram_notify_state_path", str(tmp_path / "state.json"))
        update, context, reply = _update_stub(args=[])
        await telegram_bot.notify_command(update, context)
        assert "Notifications" in reply.call_args.args[0]

    @pytest.mark.asyncio
    async def test_toggle_all_off_writes_state(self, tmp_path, monkeypatch):
        from app.config import settings
        path = tmp_path / "state.json"
        monkeypatch.setattr(settings, "telegram_notify_state_path", str(path))

        update, context, reply = _update_stub(args=["off"])
        await telegram_bot.notify_command(update, context)

        state = json.loads(path.read_text())
        assert state["enabled"] is False

    @pytest.mark.asyncio
    async def test_mute_specific_event(self, tmp_path, monkeypatch):
        from app.config import settings
        path = tmp_path / "state.json"
        monkeypatch.setattr(settings, "telegram_notify_state_path", str(path))

        update, context, reply = _update_stub(args=["off", "video.failed"])
        await telegram_bot.notify_command(update, context)

        state = json.loads(path.read_text())
        assert "video.failed" in state["muted_events"]

    @pytest.mark.asyncio
    async def test_rejects_unknown_event(self, tmp_path, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "telegram_notify_state_path", str(tmp_path / "s.json"))
        update, context, reply = _update_stub(args=["off", "nonsense.event"])
        await telegram_bot.notify_command(update, context)
        assert "Unknown event" in reply.call_args.args[0]
