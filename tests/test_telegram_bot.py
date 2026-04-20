"""Tests for Phase 4: Telegram bot."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.chat_session import ChatSession
from app.telegram_bot import (
    _release_bot_lock,
    DENIED_TEXT,
    _format_source_citation,
    _is_user_allowed,
    acquire_bot_lock,
    create_bot_application,
    format_response_with_sources,
    handle_message,
    new_command,
    sessions_command,
    split_message,
    start_command,
    status_command,
    videos_command,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_update(user_id=123, chat_id=456, text="Hello"):
    """Create a mock Telegram Update."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_session(title="Test Session", chat_id=456):
    session = MagicMock(spec=ChatSession)
    session.id = uuid.uuid4()
    session.title = title
    session.platform = "telegram"
    session.telegram_chat_id = chat_id
    session.created_at = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
    session.updated_at = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
    session.messages = []
    return session


class FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None


class FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return FakeScalars(self._items)

    def scalar(self):
        return self._items

    def scalar_one(self):
        return self._items[0] if isinstance(self._items, list) else self._items


class FakeDB:
    def __init__(self, results=None):
        self._results = list(results or [])
        self._idx = 0
        self.added = []

    async def execute(self, *args, **kwargs):
        if self._idx < len(self._results):
            val = self._results[self._idx]
            self._idx += 1
            return val
        return FakeResult([])

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def refresh(self, obj):
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = uuid.uuid4()

    async def close(self):
        pass


# ---------------------------------------------------------------------------
# Access control tests
# ---------------------------------------------------------------------------


class TestAccessControl:
    def test_allowed_when_list_empty(self):
        with patch("app.telegram_bot.settings") as mock_settings:
            mock_settings.telegram_allowed_users = []
            assert _is_user_allowed(999) is True

    def test_allowed_when_in_list(self):
        with patch("app.telegram_bot.settings") as mock_settings:
            mock_settings.telegram_allowed_users = [123, 456]
            assert _is_user_allowed(123) is True

    def test_denied_when_not_in_list(self):
        with patch("app.telegram_bot.settings") as mock_settings:
            mock_settings.telegram_allowed_users = [123, 456]
            assert _is_user_allowed(789) is False

    @pytest.mark.asyncio
    async def test_start_denied(self):
        update = _make_update(user_id=999)
        with patch("app.telegram_bot._is_user_allowed", return_value=False):
            await start_command(update, MagicMock())
        update.message.reply_text.assert_called_once_with(DENIED_TEXT)

    @pytest.mark.asyncio
    async def test_new_denied(self):
        update = _make_update(user_id=999)
        with patch("app.telegram_bot._is_user_allowed", return_value=False):
            await new_command(update, MagicMock())
        update.message.reply_text.assert_called_once_with(DENIED_TEXT)

    @pytest.mark.asyncio
    async def test_message_denied(self):
        update = _make_update(user_id=999)
        with patch("app.telegram_bot._is_user_allowed", return_value=False):
            await handle_message(update, MagicMock())
        update.message.reply_text.assert_called_once_with(DENIED_TEXT)


# ---------------------------------------------------------------------------
# Command tests
# ---------------------------------------------------------------------------


class TestStartCommand:
    @pytest.mark.asyncio
    async def test_start_welcome(self):
        update = _make_update()
        with patch("app.telegram_bot._is_user_allowed", return_value=True):
            await start_command(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "Welcome" in reply
        assert "/new" in reply


class TestNewCommand:
    @pytest.mark.asyncio
    async def test_creates_session(self):
        update = _make_update(chat_id=456)
        db = FakeDB()
        with (
            patch("app.telegram_bot._is_user_allowed", return_value=True),
            patch("app.telegram_bot._get_db", return_value=db),
        ):
            await new_command(update, MagicMock())
        assert len(db.added) == 1
        session = db.added[0]
        assert session.platform == "telegram"
        assert session.telegram_chat_id == 456
        reply = update.message.reply_text.call_args[0][0]
        assert "New chat session created" in reply


class TestSessionsCommand:
    @pytest.mark.asyncio
    async def test_no_sessions(self):
        update = _make_update()
        db = FakeDB(results=[FakeResult([])])
        with (
            patch("app.telegram_bot._is_user_allowed", return_value=True),
            patch("app.telegram_bot._get_db", return_value=db),
        ):
            await sessions_command(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "No sessions found" in reply

    @pytest.mark.asyncio
    async def test_lists_sessions(self):
        session = _make_session(title="My Chat")
        update = _make_update()
        db = FakeDB(results=[FakeResult([session])])
        with (
            patch("app.telegram_bot._is_user_allowed", return_value=True),
            patch("app.telegram_bot._get_db", return_value=db),
        ):
            await sessions_command(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "My Chat" in reply


class TestStatusCommand:
    @pytest.mark.asyncio
    async def test_shows_counts(self):
        update = _make_update()
        db = FakeDB(results=[FakeResult(42), FakeResult(30)])
        with (
            patch("app.telegram_bot._is_user_allowed", return_value=True),
            patch("app.telegram_bot._get_db", return_value=db),
        ):
            await status_command(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "42" in reply
        assert "30" in reply


class TestVideosCommand:
    @pytest.mark.asyncio
    async def test_no_videos(self):
        update = _make_update()
        db = FakeDB(results=[FakeResult([])])
        with (
            patch("app.telegram_bot._is_user_allowed", return_value=True),
            patch("app.telegram_bot._get_db", return_value=db),
        ):
            await videos_command(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "No chat-enabled videos" in reply


# ---------------------------------------------------------------------------
# Message handling tests
# ---------------------------------------------------------------------------


class TestHandleMessage:
    @pytest.mark.asyncio
    async def test_auto_creates_session_and_responds(self):
        update = _make_update(text="What is this about?")
        session = _make_session(title=None)
        # First execute: find session -> none. Second: bounded messages query (empty, new session)
        db = FakeDB(results=[FakeResult([]), FakeResult([])])
        # Override add to capture the new session
        original_add = db.add

        def track_add(obj):
            original_add(obj)
            if isinstance(obj, ChatSession):
                obj.id = session.id

        db.add = track_add

        chat_result = {
            "content": "This is about testing.",
            "sources": [],
            "model": "test-model",
            "prompt_tokens": 10,
            "completion_tokens": 20,
        }
        with (
            patch("app.telegram_bot._is_user_allowed", return_value=True),
            patch("app.telegram_bot._get_db", return_value=db),
            patch("app.telegram_bot.chat_with_context", return_value=chat_result),
        ):
            await handle_message(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "This is about testing." in reply

    @pytest.mark.asyncio
    async def test_uses_existing_session(self):
        update = _make_update(text="Follow up question")
        session = _make_session(title="Existing Chat")
        # First execute: find session -> found. Second: bounded messages query (empty)
        db = FakeDB(results=[FakeResult([session]), FakeResult([])])

        chat_result = {
            "content": "Follow up answer.",
            "sources": [
                {"video_title": "Cool Video", "start_time": 125, "video_id": "abc"},
            ],
            "model": "test-model",
            "prompt_tokens": 10,
            "completion_tokens": 20,
        }
        with (
            patch("app.telegram_bot._is_user_allowed", return_value=True),
            patch("app.telegram_bot._get_db", return_value=db),
            patch("app.telegram_bot.chat_with_context", return_value=chat_result),
        ):
            await handle_message(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "Follow up answer." in reply
        assert "\U0001f4f9 Cool Video @ 2:05" in reply


# ---------------------------------------------------------------------------
# Response formatting tests
# ---------------------------------------------------------------------------


class TestFormatResponse:
    def test_no_sources(self):
        result = format_response_with_sources("Hello", [])
        assert result == "Hello"

    def test_with_sources(self):
        sources = [
            {"video_title": "Video A", "start_time": 90},
            {"video_title": "Video B", "start_time": None},
        ]
        result = format_response_with_sources("Answer text", sources)
        assert "Sources:" in result
        assert "[\U0001f4f9 Video A @ 1:30]" in result
        assert "[\U0001f4f9 Video B]" in result

    def test_deduplicates_sources(self):
        sources = [
            {"video_title": "Video A", "start_time": 90},
            {"video_title": "Video A", "start_time": 90},
        ]
        result = format_response_with_sources("Answer", sources)
        assert result.count("[\U0001f4f9 Video A @ 1:30]") == 1


# ---------------------------------------------------------------------------
# Message splitting tests
# ---------------------------------------------------------------------------


class TestSplitMessage:
    def test_short_message_no_split(self):
        assert split_message("short") == ["short"]

    def test_exact_limit(self):
        text = "x" * 4096
        assert split_message(text) == [text]

    def test_splits_at_newline(self):
        text = "a" * 4000 + "\n" + "b" * 200
        chunks = split_message(text)
        assert len(chunks) == 2
        assert chunks[0] == "a" * 4000
        assert chunks[1] == "b" * 200

    def test_splits_at_space(self):
        text = "word " * 1000  # 5000 chars
        chunks = split_message(text)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 4096

    def test_hard_split_no_whitespace(self):
        text = "x" * 5000
        chunks = split_message(text)
        assert len(chunks) == 2
        assert len(chunks[0]) == 4096
        assert len(chunks[1]) == 904

    def test_splits_long_message_multiple_chunks(self):
        text = "a" * 10000
        chunks = split_message(text)
        assert len(chunks) == 3
        total = sum(len(c) for c in chunks)
        assert total == 10000


# ---------------------------------------------------------------------------
# Source citation formatting tests
# ---------------------------------------------------------------------------


class TestFormatSourceCitation:
    def test_with_seconds_only(self):
        result = _format_source_citation({"video_title": "Test", "start_time": 45})
        assert result == "[\U0001f4f9 Test @ 0:45]"

    def test_with_minutes_and_seconds(self):
        result = _format_source_citation({"video_title": "Test", "start_time": 125})
        assert result == "[\U0001f4f9 Test @ 2:05]"

    def test_with_hours(self):
        result = _format_source_citation({"video_title": "Test", "start_time": 3661})
        assert result == "[\U0001f4f9 Test @ 1:01:01]"

    def test_no_start_time(self):
        result = _format_source_citation({"video_title": "Test", "start_time": None})
        assert result == "[\U0001f4f9 Test]"

    def test_missing_title(self):
        result = _format_source_citation({"start_time": 10})
        assert result == "[\U0001f4f9 Unknown @ 0:10]"

    def test_summary_source(self):
        result = _format_source_citation({"video_title": "Test", "source_type": "summary"})
        assert result == "[\U0001f4f9 Test Summary]"


# ---------------------------------------------------------------------------
# Videos command — listing videos
# ---------------------------------------------------------------------------


class TestVideosCommandListing:
    @pytest.mark.asyncio
    async def test_lists_videos(self):
        update = _make_update()
        db = FakeDB(results=[FakeResult(["Video One", "Video Two"])])
        with (
            patch("app.telegram_bot._is_user_allowed", return_value=True),
            patch("app.telegram_bot._get_db", return_value=db),
        ):
            await videos_command(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "Video One" in reply
        assert "Video Two" in reply
        assert "2" in reply  # count


# ---------------------------------------------------------------------------
# Access control — additional denied commands
# ---------------------------------------------------------------------------


class TestAccessControlAdditional:
    @pytest.mark.asyncio
    async def test_sessions_denied(self):
        update = _make_update(user_id=999)
        with patch("app.telegram_bot._is_user_allowed", return_value=False):
            await sessions_command(update, MagicMock())
        update.message.reply_text.assert_called_once_with(DENIED_TEXT)

    @pytest.mark.asyncio
    async def test_status_denied(self):
        update = _make_update(user_id=999)
        with patch("app.telegram_bot._is_user_allowed", return_value=False):
            await status_command(update, MagicMock())
        update.message.reply_text.assert_called_once_with(DENIED_TEXT)

    @pytest.mark.asyncio
    async def test_videos_denied(self):
        update = _make_update(user_id=999)
        with patch("app.telegram_bot._is_user_allowed", return_value=False):
            await videos_command(update, MagicMock())
        update.message.reply_text.assert_called_once_with(DENIED_TEXT)


# ---------------------------------------------------------------------------
# Handle message — edge cases
# ---------------------------------------------------------------------------


class TestHandleMessageEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_text_ignored(self):
        update = _make_update(text=None)
        update.message.text = None
        with patch("app.telegram_bot._is_user_allowed", return_value=True):
            await handle_message(update, MagicMock())
        # Should not attempt to reply (no DB call, no error)
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_in_chat_returns_error_message(self):
        update = _make_update(text="Hello")
        session = _make_session(title="Existing")
        db = FakeDB(results=[FakeResult([session]), FakeResult(session)])
        with (
            patch("app.telegram_bot._is_user_allowed", return_value=True),
            patch("app.telegram_bot._get_db", return_value=db),
            patch(
                "app.telegram_bot.chat_with_context",
                side_effect=RuntimeError("LLM down"),
            ),
        ):
            await handle_message(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "error occurred" in reply

    @pytest.mark.asyncio
    async def test_auto_title_from_first_message(self):
        update = _make_update(text="Short question")
        # Use an existing session with title=None so the same object is reused
        session = _make_session(title=None)
        # First query returns the session; second reloads it (same object)
        db = FakeDB(results=[FakeResult([session]), FakeResult(session)])

        chat_result = {
            "content": "Answer.",
            "sources": [],
            "model": "m",
            "prompt_tokens": 1,
            "completion_tokens": 1,
        }
        with (
            patch("app.telegram_bot._is_user_allowed", return_value=True),
            patch("app.telegram_bot._get_db", return_value=db),
            patch("app.telegram_bot.chat_with_context", return_value=chat_result),
        ):
            await handle_message(update, MagicMock())
        # Session title should be set from the first message
        assert session.title == "Short question"

    @pytest.mark.asyncio
    async def test_long_title_truncated(self):
        long_text = "x" * 100
        update = _make_update(text=long_text)
        session = _make_session(title=None)
        db = FakeDB(results=[FakeResult([session]), FakeResult(session)])

        chat_result = {
            "content": "OK.",
            "sources": [],
            "model": "m",
            "prompt_tokens": 1,
            "completion_tokens": 1,
        }
        with (
            patch("app.telegram_bot._is_user_allowed", return_value=True),
            patch("app.telegram_bot._get_db", return_value=db),
            patch("app.telegram_bot.chat_with_context", return_value=chat_result),
        ):
            await handle_message(update, MagicMock())
        assert session.title == "x" * 50 + "..."


# ---------------------------------------------------------------------------
# Bot application creation
# ---------------------------------------------------------------------------


class TestCreateBotApplication:
    def test_raises_without_token(self):
        with patch("app.telegram_bot.settings") as mock_settings:
            mock_settings.telegram_bot_token = ""
            with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
                create_bot_application()

    def test_creates_application_with_token(self):
        with patch("app.telegram_bot.settings") as mock_settings:
            mock_settings.telegram_bot_token = "fake-token:12345"
            app = create_bot_application()
            # Expected: 23 commands + 1 callback_query + 1 message handler.
            # See _build_command_manifest() in app/telegram_bot.py.
            assert len(app.handlers[0]) == 25


class TestBotLock:
    def teardown_method(self):
        _release_bot_lock()

    def test_acquire_bot_lock_allows_first_holder(self, tmp_path):
        lock_path = tmp_path / "telegram.lock"
        assert acquire_bot_lock(lock_path) is True

    def test_acquire_bot_lock_rejects_second_holder(self, tmp_path):
        lock_path = tmp_path / "telegram.lock"
        first_handle = lock_path.open("a+")
        import fcntl

        fcntl.flock(first_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            assert acquire_bot_lock(lock_path) is False
        finally:
            first_handle.close()


# ---------------------------------------------------------------------------
# Format response — max 5 sources
# ---------------------------------------------------------------------------


class TestFormatResponseMaxSources:
    def test_limits_to_five_sources(self):
        sources = [
            {"video_title": f"Video {i}", "start_time": i * 10}
            for i in range(10)
        ]
        result = format_response_with_sources("Answer", sources)
        assert result.count("\U0001f4f9") == 5
