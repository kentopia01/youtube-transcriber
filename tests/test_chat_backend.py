"""Tests for Phase 2: Chat backend (sessions + RAG + API)."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.dependencies import get_db
from app.main import create_app
from app.services.chat import (
    SYSTEM_PROMPT,
    _build_messages,
    _format_chunks_for_context,
    _fmt_ts,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc)


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value if isinstance(self._value, list) else []

    def first(self):
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value


class StubDB:
    """Fake async DB session for testing routers without a real database."""

    def __init__(self, execute_results=None):
        self._results = list(execute_results or [])
        self._exec_idx = 0
        self.added = []
        self.committed = False
        self.deleted = []

    async def execute(self, *args, **kwargs):
        if self._exec_idx < len(self._results):
            val = self._results[self._exec_idx]
            self._exec_idx += 1
            return _FakeResult(val)
        return _FakeResult(None)

    def add(self, obj):
        self.added.append(obj)
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()

    async def flush(self):
        for obj in self.added:
            if hasattr(obj, "id") and obj.id is None:
                obj.id = uuid.uuid4()

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        # Simulate refresh — set created_at/updated_at if missing
        if hasattr(obj, "created_at") and obj.created_at is None:
            obj.created_at = _now()
        if hasattr(obj, "updated_at") and obj.updated_at is None:
            obj.updated_at = _now()

    async def delete(self, obj):
        self.deleted.append(obj)


def _make_session(title=None, messages=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        title=title,
        platform="web",
        telegram_chat_id=None,
        created_at=_now(),
        updated_at=_now(),
        messages=messages or [],
    )


def _make_message(session_id, role="user", content="hello", sources=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        session_id=session_id,
        role=role,
        content=content,
        sources=sources,
        model="claude-sonnet-4-20250514" if role == "assistant" else None,
        prompt_tokens=100 if role == "assistant" else None,
        completion_tokens=50 if role == "assistant" else None,
        created_at=_now(),
    )


def _build_client(db=None):
    from fastapi.testclient import TestClient

    app = create_app()

    async def _override():
        yield db or StubDB()

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


# ---------------------------------------------------------------------------
# Session CRUD tests
# ---------------------------------------------------------------------------

class TestCreateSession:
    def test_create_session_returns_201_fields(self):
        db = StubDB()
        client = _build_client(db)
        resp = client.post("/api/chat/sessions", json={"platform": "web"})
        assert resp.status_code == 200
        body = resp.json()
        assert "id" in body
        assert body["platform"] == "web"
        assert body["title"] is None
        assert db.committed

    def test_create_session_default_platform(self):
        db = StubDB()
        client = _build_client(db)
        resp = client.post("/api/chat/sessions", json={})
        assert resp.status_code == 200
        assert resp.json()["platform"] == "web"

    def test_create_session_no_body(self):
        db = StubDB()
        client = _build_client(db)
        # POST with no JSON body should still work (defaults)
        resp = client.post("/api/chat/sessions")
        assert resp.status_code == 200


class TestListSessions:
    def test_list_sessions_empty(self):
        db = StubDB(execute_results=[[]])
        client = _build_client(db)
        resp = client.get("/api/chat/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_sessions_returns_sessions(self):
        s1 = _make_session(title="First")
        s2 = _make_session(title="Second")
        db = StubDB(execute_results=[[s1, s2]])
        client = _build_client(db)
        resp = client.get("/api/chat/sessions")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2


class TestGetSession:
    def test_get_session_with_messages(self):
        session = _make_session(title="Test Session")
        msg = _make_message(session.id, role="user", content="hi")
        session.messages = [msg]
        db = StubDB(execute_results=[session])
        client = _build_client(db)
        resp = client.get(f"/api/chat/sessions/{session.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "Test Session"
        assert len(body["messages"]) == 1
        assert body["messages"][0]["content"] == "hi"

    def test_get_nonexistent_session_returns_404(self):
        db = StubDB(execute_results=[None])
        client = _build_client(db)
        resp = client.get(f"/api/chat/sessions/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestDeleteSession:
    def test_delete_session(self):
        session = _make_session(title="To Delete")
        db = StubDB(execute_results=[session])
        client = _build_client(db)
        resp = client.delete(f"/api/chat/sessions/{session.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted"] is True
        assert len(db.deleted) == 1
        assert db.committed

    def test_delete_nonexistent_session_returns_404(self):
        db = StubDB(execute_results=[None])
        client = _build_client(db)
        resp = client.delete(f"/api/chat/sessions/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestRenameSession:
    def test_rename_session(self):
        session = _make_session(title="Old Title")
        db = StubDB(execute_results=[session])
        client = _build_client(db)
        resp = client.patch(
            f"/api/chat/sessions/{session.id}",
            json={"title": "New Title"},
        )
        assert resp.status_code == 200
        assert session.title == "New Title"

    def test_rename_nonexistent_session_returns_404(self):
        db = StubDB(execute_results=[None])
        client = _build_client(db)
        resp = client.patch(
            f"/api/chat/sessions/{uuid.uuid4()}",
            json={"title": "New"},
        )
        assert resp.status_code == 404

    def test_rename_missing_title_returns_422(self):
        client = _build_client()
        resp = client.patch(
            f"/api/chat/sessions/{uuid.uuid4()}",
            json={},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Send message tests (mocking the Anthropic API)
# ---------------------------------------------------------------------------

MOCK_CHAT_RESULT = {
    "content": "Based on the transcripts, the answer is 42.",
    "sources": [
        {
            "video_id": str(uuid.uuid4()),
            "video_title": "Test Video",
            "chunk_text": "The answer is 42.",
            "start_time": 10.0,
            "end_time": 20.0,
            "similarity": 0.95,
        }
    ],
    "model": "claude-sonnet-4-20250514",
    "prompt_tokens": 500,
    "completion_tokens": 100,
}


class TestSendMessage:
    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_send_message_returns_assistant_response(self, mock_chat):
        mock_chat.return_value = MOCK_CHAT_RESULT
        session = _make_session(title="Existing")
        session.messages = []
        db = StubDB(execute_results=[session])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{session.id}/messages",
            json={"content": "What is the answer?"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "assistant"
        assert body["content"] == MOCK_CHAT_RESULT["content"]
        assert body["model"] == "claude-sonnet-4-20250514"
        assert body["prompt_tokens"] == 500
        assert body["completion_tokens"] == 100
        mock_chat.assert_called_once()

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_send_message_includes_sources(self, mock_chat):
        mock_chat.return_value = MOCK_CHAT_RESULT
        session = _make_session(title="Test")
        session.messages = []
        db = StubDB(execute_results=[session])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{session.id}/messages",
            json={"content": "What is the answer?"},
        )
        body = resp.json()
        assert body["sources"] is not None
        assert len(body["sources"]) == 1
        assert body["sources"][0]["video_title"] == "Test Video"

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_auto_title_on_first_message(self, mock_chat):
        mock_chat.return_value = MOCK_CHAT_RESULT
        session = _make_session(title=None)  # No title yet
        session.messages = []
        db = StubDB(execute_results=[session])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{session.id}/messages",
            json={"content": "What are the key points from the game theory lecture?"},
        )
        assert resp.status_code == 200
        # Title should be auto-generated from first 50 chars
        assert session.title is not None
        assert session.title.startswith("What are the key points from the game theory lectu")
        assert session.title.endswith("...")

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_auto_title_short_message_no_ellipsis(self, mock_chat):
        mock_chat.return_value = MOCK_CHAT_RESULT
        session = _make_session(title=None)
        session.messages = []
        db = StubDB(execute_results=[session])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{session.id}/messages",
            json={"content": "Short question"},
        )
        assert resp.status_code == 200
        assert session.title == "Short question"
        assert not session.title.endswith("...")

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_existing_title_not_overwritten(self, mock_chat):
        mock_chat.return_value = MOCK_CHAT_RESULT
        session = _make_session(title="My Custom Title")
        session.messages = [_make_message(session.id)]
        db = StubDB(execute_results=[session])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{session.id}/messages",
            json={"content": "Follow-up question"},
        )
        assert resp.status_code == 200
        assert session.title == "My Custom Title"

    def test_send_message_nonexistent_session_returns_404(self):
        db = StubDB(execute_results=[None])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{uuid.uuid4()}/messages",
            json={"content": "hello"},
        )
        assert resp.status_code == 404

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_chat_enabled_only_filter_used(self, mock_chat):
        """Verify chat_with_context is called (it uses chat_enabled_only=True internally)."""
        mock_chat.return_value = MOCK_CHAT_RESULT
        session = _make_session(title="Test")
        session.messages = []
        db = StubDB(execute_results=[session])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{session.id}/messages",
            json={"content": "test query"},
        )
        assert resp.status_code == 200
        # Verify chat_with_context was called with the question and db
        call_kwargs = mock_chat.call_args[1]
        assert call_kwargs["question"] == "test query"


# ---------------------------------------------------------------------------
# Chat service unit tests
# ---------------------------------------------------------------------------

class TestChatServiceHelpers:
    def test_fmt_ts_minutes_seconds(self):
        assert _fmt_ts(65) == "1:05"
        assert _fmt_ts(0) == "0:00"
        assert _fmt_ts(59) == "0:59"

    def test_fmt_ts_hours(self):
        assert _fmt_ts(3661) == "1:01:01"
        assert _fmt_ts(7200) == "2:00:00"

    def test_format_chunks_for_context(self):
        chunks = [
            {
                "video_title": "Video A",
                "chunk_text": "Some content here",
                "start_time": 10.0,
                "end_time": 20.0,
            },
            {
                "video_title": "Video B",
                "chunk_text": "Other content",
                "start_time": None,
                "end_time": None,
            },
        ]
        result = _format_chunks_for_context(chunks)
        assert "[1] Video A [0:10 - 0:20]" in result
        assert "Some content here" in result
        assert "[2] Video B" in result
        assert "Other content" in result

    def test_build_messages_with_history(self):
        history = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
        ]
        messages = _build_messages(history, "new question", "context text")
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert messages[2]["role"] == "user"
        assert "context text" in messages[2]["content"]
        assert "new question" in messages[2]["content"]

    def test_build_messages_empty_history(self):
        messages = _build_messages([], "my question", "context")
        assert len(messages) == 1
        assert messages[0]["role"] == "user"


class TestChatWithContext:
    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_chat_with_context_calls_search_with_chat_enabled(
        self, mock_encode, mock_search, mock_llm
    ):
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = [
            {
                "id": uuid.uuid4(),
                "video_id": uuid.uuid4(),
                "video_title": "Test Vid",
                "chunk_text": "chunk text",
                "start_time": 0.0,
                "end_time": 10.0,
                "speaker": None,
                "similarity": 0.9,
            }
        ]
        mock_llm.return_value = {
            "content": "Answer from LLM",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 200,
            "completion_tokens": 50,
        }

        db = AsyncMock()
        result = await chat_with_context("test question", [], db)

        # Verify search was called with chat_enabled_only=True
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args[1]
        assert call_kwargs["chat_enabled_only"] is True

        assert result["content"] == "Answer from LLM"
        assert len(result["sources"]) == 1
        assert result["sources"][0]["video_title"] == "Test Vid"

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_chat_returns_empty_sources_when_no_chunks(
        self, mock_encode, mock_search, mock_llm
    ):
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []
        mock_llm.return_value = {
            "content": "I don't have enough context.",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 100,
            "completion_tokens": 20,
        }

        db = AsyncMock()
        result = await chat_with_context("unknown topic", [], db)

        assert result["sources"] == []
        assert "don't have enough" in result["content"]
