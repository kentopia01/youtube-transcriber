"""Tests for Phase 2: Chat backend (sessions + RAG + API)."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.dependencies import get_db
from app.main import create_app
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession


# ---------------------------------------------------------------------------
# DB helpers — reuse StubDB pattern from test_chat_toggle
# ---------------------------------------------------------------------------

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
    def __init__(self, execute_results=None):
        self._results = list(execute_results or [])
        self.added = []
        self.committed = False
        self._exec_idx = 0
        self._deleted = []

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
        if hasattr(obj, "created_at") and not obj.created_at:
            obj.created_at = datetime.now(timezone.utc)
        if hasattr(obj, "updated_at") and not obj.updated_at:
            obj.updated_at = datetime.now(timezone.utc)
        if hasattr(obj, "platform") and not obj.platform:
            obj.platform = "web"

    async def flush(self):
        pass

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        if hasattr(obj, "created_at") and not obj.created_at:
            obj.created_at = datetime.now(timezone.utc)
        if hasattr(obj, "updated_at") and not obj.updated_at:
            obj.updated_at = datetime.now(timezone.utc)

    async def delete(self, obj):
        self._deleted.append(obj)


def _build_client(db=None):
    from fastapi.testclient import TestClient

    app = create_app()

    async def _override():
        yield db or StubDB()

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def _make_session(title="Test Chat", sid=None):
    return SimpleNamespace(
        id=sid or uuid.uuid4(),
        title=title,
        platform="web",
        telegram_chat_id=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        messages=[],
    )


def _make_message(session_id, role="user", content="Hello", sources=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        session_id=session_id,
        role=role,
        content=content,
        sources=sources,
        model="claude-sonnet-4-20250514" if role == "assistant" else None,
        prompt_tokens=100 if role == "assistant" else None,
        completion_tokens=50 if role == "assistant" else None,
        created_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Session CRUD tests
# ---------------------------------------------------------------------------

class TestCreateSession:
    def test_create_session_default(self):
        db = StubDB()
        client = _build_client(db)
        resp = client.post("/api/chat/sessions", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert "id" in body
        assert body["platform"] == "web"
        assert db.committed

    def test_create_session_with_title(self):
        db = StubDB()
        client = _build_client(db)
        resp = client.post("/api/chat/sessions", json={"title": "My Chat"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "My Chat"

    def test_create_session_no_body(self):
        db = StubDB()
        client = _build_client(db)
        resp = client.post("/api/chat/sessions")
        assert resp.status_code == 200


class TestListSessions:
    def test_list_sessions_empty(self):
        db = StubDB(execute_results=[[]])
        client = _build_client(db)
        resp = client.get("/api/chat/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_sessions_returns_items(self):
        s1 = _make_session("Chat A")
        s2 = _make_session("Chat B")
        db = StubDB(execute_results=[[s1, s2]])
        client = _build_client(db)
        resp = client.get("/api/chat/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2


class TestGetSession:
    def test_get_session_found(self):
        s = _make_session("Test")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.get(f"/api/chat/sessions/{s.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(s.id)
        assert body["title"] == "Test"
        assert body["messages"] == []

    def test_get_session_with_messages(self):
        s = _make_session("Test")
        msg = _make_message(s.id, "user", "Hello")
        s.messages = [msg]
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.get(f"/api/chat/sessions/{s.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["messages"]) == 1
        assert body["messages"][0]["content"] == "Hello"

    def test_get_session_not_found(self):
        db = StubDB(execute_results=[None])
        client = _build_client(db)
        resp = client.get(f"/api/chat/sessions/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestDeleteSession:
    def test_delete_session(self):
        s = _make_session("To Delete")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.delete(f"/api/chat/sessions/{s.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted"] is True
        assert db._deleted == [s]

    def test_delete_session_not_found(self):
        db = StubDB(execute_results=[None])
        client = _build_client(db)
        resp = client.delete(f"/api/chat/sessions/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestRenameSession:
    def test_rename_session(self):
        s = _make_session("Old Title")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.patch(
            f"/api/chat/sessions/{s.id}",
            json={"title": "New Title"},
        )
        assert resp.status_code == 200
        assert s.title == "New Title"

    def test_rename_session_not_found(self):
        db = StubDB(execute_results=[None])
        client = _build_client(db)
        resp = client.patch(
            f"/api/chat/sessions/{uuid.uuid4()}",
            json={"title": "X"},
        )
        assert resp.status_code == 404

    def test_rename_session_missing_title_returns_422(self):
        client = _build_client()
        resp = client.patch(
            f"/api/chat/sessions/{uuid.uuid4()}",
            json={},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Send message tests
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
        s = _make_session(title=None)
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "What is the meaning of life?"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "assistant"
        assert body["content"] == MOCK_CHAT_RESULT["content"]
        assert body["model"] == "claude-sonnet-4-20250514"
        assert body["prompt_tokens"] == 500
        assert body["completion_tokens"] == 100

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_send_message_returns_sources(self, mock_chat):
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title="Existing")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "Tell me about it"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["sources"] is not None
        assert len(body["sources"]) == 1
        src = body["sources"][0]
        assert src["video_title"] == "Test Video"
        assert src["start_time"] == 10.0
        assert src["similarity"] == 0.95

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_auto_title_from_first_message(self, mock_chat):
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title=None)
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "What is the meaning of life?"},
        )
        # Title auto-generated from first message
        assert s.title == "What is the meaning of life?"

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_auto_title_truncated_at_50_chars(self, mock_chat):
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title=None)
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        long_msg = "A" * 60
        client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": long_msg},
        )
        assert s.title == "A" * 50 + "..."

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_existing_title_not_overwritten(self, mock_chat):
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title="Keep This")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "Something new"},
        )
        assert s.title == "Keep This"

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_conversation_history_passed_to_chat(self, mock_chat):
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title="Chat")
        msg1 = _make_message(s.id, "user", "First question")
        msg2 = _make_message(s.id, "assistant", "First answer")
        s.messages = [msg1, msg2]
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "Follow-up question"},
        )
        mock_chat.assert_called_once()
        call_kwargs = mock_chat.call_args[1]
        history = call_kwargs["history"]
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "First question"
        assert history[1]["role"] == "assistant"
        assert history[1]["content"] == "First answer"

    def test_send_message_session_not_found(self):
        db = StubDB(execute_results=[None])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{uuid.uuid4()}/messages",
            json={"content": "Hello"},
        )
        assert resp.status_code == 404

    def test_send_message_missing_content_returns_422(self):
        client = _build_client()
        resp = client.post(
            f"/api/chat/sessions/{uuid.uuid4()}/messages",
            json={},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Chat service unit tests
# ---------------------------------------------------------------------------

class TestChatService:
    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_chat_with_context_calls_search_with_chat_enabled(
        self, mock_encode, mock_search, mock_llm,
    ):
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = [
            {
                "id": uuid.uuid4(),
                "video_id": uuid.uuid4(),
                "video_title": "Test",
                "chunk_text": "Some text",
                "start_time": 0.0,
                "end_time": 10.0,
                "speaker": None,
                "similarity": 0.9,
            }
        ]
        mock_llm.return_value = {
            "content": "Answer",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }

        db = AsyncMock()
        result = await chat_with_context("question", [], db)

        # Verify chat_enabled_only=True was passed to search
        mock_search.assert_called_once()
        _, kwargs = mock_search.call_args
        assert kwargs["chat_enabled_only"] is True

        assert result["content"] == "Answer"
        assert len(result["sources"]) == 1
        assert result["sources"][0]["video_title"] == "Test"

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_chat_with_context_returns_correct_structure(
        self, mock_encode, mock_search, mock_llm,
    ):
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []
        mock_llm.return_value = {
            "content": "No context found",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 50,
            "completion_tokens": 20,
        }

        db = AsyncMock()
        result = await chat_with_context("question", [], db)

        assert "content" in result
        assert "sources" in result
        assert "model" in result
        assert "prompt_tokens" in result
        assert "completion_tokens" in result
        assert result["sources"] == []

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_history_trimmed_to_max(
        self, mock_encode, mock_search, mock_llm,
    ):
        from app.services.chat import chat_with_context, _build_messages

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []
        mock_llm.return_value = {
            "content": "Answer",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 50,
            "completion_tokens": 20,
        }

        # Create 30 messages (exceeds chat_max_history * 2 = 20)
        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
            for i in range(30)
        ]

        db = AsyncMock()
        await chat_with_context("question", history, db)

        # Verify _call_anthropic was called with trimmed history
        call_args = mock_llm.call_args
        messages = call_args[0][1]  # second positional arg is messages
        # Last message is the current question, preceding are history
        # History should be trimmed to last 20 (chat_max_history * 2)
        assert len(messages) == 21  # 20 history + 1 current question


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestFormatChunks:
    def test_format_chunks_basic(self):
        from app.services.chat import _format_chunks_for_context

        chunks = [
            {
                "video_title": "Video A",
                "chunk_text": "Hello world",
                "start_time": 65.0,
                "end_time": 75.0,
            }
        ]
        result = _format_chunks_for_context(chunks)
        assert "[1] Video A [1:05 - 1:15]" in result
        assert "Hello world" in result

    def test_format_chunks_no_timestamps(self):
        from app.services.chat import _format_chunks_for_context

        chunks = [
            {
                "video_title": "Video B",
                "chunk_text": "No time",
                "start_time": None,
                "end_time": None,
            }
        ]
        result = _format_chunks_for_context(chunks)
        assert "[1] Video B\n" in result

    def test_format_timestamp_with_hours(self):
        from app.services.chat import _fmt_ts

        assert _fmt_ts(3661) == "1:01:01"
        assert _fmt_ts(0) == "0:00"
        assert _fmt_ts(90) == "1:30"


class TestBuildMessages:
    def test_build_messages_no_history(self):
        from app.services.chat import _build_messages

        messages = _build_messages([], "What?", "context text")
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "context text" in messages[0]["content"]
        assert "What?" in messages[0]["content"]

    def test_build_messages_with_history(self):
        from app.services.chat import _build_messages

        history = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        messages = _build_messages(history, "Follow up", "ctx")
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hi"
        assert messages[2]["role"] == "user"
        assert "Follow up" in messages[2]["content"]
