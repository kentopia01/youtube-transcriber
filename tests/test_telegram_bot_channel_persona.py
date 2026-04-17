"""Tests for the /channels and /ask_channel Telegram commands."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# Skip if the telegram extra isn't installed in this venv.
telegram = pytest.importorskip("telegram")

from app import telegram_bot  # noqa: E402


class _FakeScalars:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return list(self._items)


class _FakeDB:
    """Multi-call async stub: responses can be queued in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self._idx = 0

    async def execute(self, *args, **kwargs):
        r = self._responses[self._idx]
        self._idx += 1
        return r

    async def close(self):
        pass


def _persona(display, scope_id, confidence=0.7):
    return SimpleNamespace(
        id=uuid.uuid4(),
        scope_type="channel",
        scope_id=scope_id,
        display_name=display,
        confidence=confidence,
        persona_prompt=f"You are {display}.",
        style_notes={},
        exemplar_chunk_ids=[],
        source_chunk_count=10,
        videos_at_generation=3,
        refresh_after_videos=5,
        generated_at=None,
    )


def _channel(cid, name):
    return SimpleNamespace(id=uuid.UUID(cid), name=name)


def _update_stub(args=None):
    reply_mock = AsyncMock()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1),
        effective_chat=SimpleNamespace(id=42),
        message=SimpleNamespace(reply_text=reply_mock),
    )
    context = SimpleNamespace(args=args or [])
    return update, context, reply_mock


# ---------------------------------------------------------------------------
# _resolve_channel_for_persona
# ---------------------------------------------------------------------------


class TestResolveChannelForPersona:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_personas(self):
        db = _FakeDB([_FakeScalars([])])
        ch, p = await telegram_bot._resolve_channel_for_persona(db, "anything")
        assert ch is None and p is None

    @pytest.mark.asyncio
    async def test_exact_display_name_wins(self):
        cid_a = str(uuid.UUID(int=1))
        cid_b = str(uuid.UUID(int=2))
        personas = [_persona("All-In", cid_a), _persona("AllIn Side Cast", cid_b)]
        channels = [_channel(cid_a, "All-In Podcast"), _channel(cid_b, "AllIn B")]
        db = _FakeDB([_FakeScalars(personas), _FakeScalars(channels)])

        ch, p = await telegram_bot._resolve_channel_for_persona(db, "All-In")
        assert p.display_name == "All-In"
        assert ch.name == "All-In Podcast"

    @pytest.mark.asyncio
    async def test_substring_fallback(self):
        cid = str(uuid.UUID(int=3))
        personas = [_persona("My Podcast Voice", cid)]
        channels = [_channel(cid, "Some Channel")]
        db = _FakeDB([_FakeScalars(personas), _FakeScalars(channels)])

        ch, p = await telegram_bot._resolve_channel_for_persona(db, "podcast")
        assert ch.name == "Some Channel"


# ---------------------------------------------------------------------------
# channels_command
# ---------------------------------------------------------------------------


class TestChannelsCommand:
    @pytest.mark.asyncio
    async def test_empty_list(self, monkeypatch):
        update, context, reply = _update_stub()
        db = _FakeDB([_FakeScalars([])])
        monkeypatch.setattr(telegram_bot, "_get_db", AsyncMock(return_value=db))

        await telegram_bot.channels_command(update, context)
        reply.assert_awaited_once()
        assert "No channel personas yet" in reply.call_args.args[0]

    @pytest.mark.asyncio
    async def test_lists_personas(self, monkeypatch):
        cid = str(uuid.UUID(int=7))
        personas = [_persona("All-In", cid, confidence=0.9)]
        channels = [_channel(cid, "All-In")]
        db = _FakeDB([_FakeScalars(personas), _FakeScalars(channels)])
        monkeypatch.setattr(telegram_bot, "_get_db", AsyncMock(return_value=db))

        update, context, reply = _update_stub()
        await telegram_bot.channels_command(update, context)
        reply.assert_awaited_once()
        body = reply.call_args.args[0]
        assert "All-In" in body
        assert "0.90" in body


# ---------------------------------------------------------------------------
# ask_channel_command
# ---------------------------------------------------------------------------


class TestAskChannelCommand:
    @pytest.mark.asyncio
    async def test_usage_when_missing_args(self, monkeypatch):
        update, context, reply = _update_stub(args=[])
        await telegram_bot.ask_channel_command(update, context)
        reply.assert_awaited_once()
        assert "Usage" in reply.call_args.args[0]

    @pytest.mark.asyncio
    async def test_no_match_message(self, monkeypatch):
        db = _FakeDB([_FakeScalars([])])
        monkeypatch.setattr(telegram_bot, "_get_db", AsyncMock(return_value=db))
        update, context, reply = _update_stub(args=["unknown", "what", "is", "up"])
        await telegram_bot.ask_channel_command(update, context)
        reply.assert_awaited_once()
        assert "No channel persona matches" in reply.call_args.args[0]

    @pytest.mark.asyncio
    async def test_dispatches_to_chat_with_context(self, monkeypatch):
        cid = str(uuid.UUID(int=8))
        personas = [_persona("All-In", cid)]
        channels = [_channel(cid, "All-In Podcast")]
        db = _FakeDB([_FakeScalars(personas), _FakeScalars(channels)])
        monkeypatch.setattr(telegram_bot, "_get_db", AsyncMock(return_value=db))
        monkeypatch.setattr(
            telegram_bot, "get_exemplar_chunks",
            AsyncMock(return_value=[]),
        )
        chat_mock = AsyncMock(return_value={
            "content": "Hello from All-In.",
            "sources": [],
            "model": "claude-haiku-4-5",
            "prompt_tokens": 100,
            "completion_tokens": 10,
        })
        monkeypatch.setattr(telegram_bot, "chat_with_context", chat_mock)

        update, context, reply = _update_stub(args=["All-In", "what", "happened?"])
        await telegram_bot.ask_channel_command(update, context)

        chat_mock.assert_awaited_once()
        kwargs = chat_mock.call_args.kwargs
        assert kwargs["channel_id"] == uuid.UUID(cid)
        assert "All-In" in kwargs["system_prompt"]
        assert kwargs["question"] == "what happened?"

        reply.assert_awaited()
        body = reply.call_args.args[0]
        assert "All-In" in body and "Hello from All-In." in body
