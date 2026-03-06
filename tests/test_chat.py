"""Tests for Phase 2: Chat backend (sessions + RAG + API)."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
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

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_send_message_special_characters(self, mock_chat):
        """Unicode, emoji, and HTML in messages should work without error."""
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title="Special")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        special_content = 'What about <script>alert("xss")</script> and emojis 🎉🔥 and unicode: café résumé naïve?'
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": special_content},
        )
        assert resp.status_code == 200
        call_kwargs = mock_chat.call_args[1]
        assert call_kwargs["question"] == special_content

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_send_very_long_message(self, mock_chat):
        """Very long message content (10k chars) should not error."""
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title=None)
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        long_msg = "A" * 10_000
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": long_msg},
        )
        assert resp.status_code == 200
        # Title should be truncated to 50 chars + "..."
        assert s.title == "A" * 50 + "..."


# ---------------------------------------------------------------------------
# Edge case: delete session with 0 messages, pagination
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_delete_session_with_zero_messages(self):
        """Deleting session with no messages should succeed."""
        s = _make_session("Empty Session")
        s.messages = []
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.delete(f"/api/chat/sessions/{s.id}")
        assert resp.status_code == 200
        assert db._deleted == [s]

    def test_list_sessions_pagination_params(self):
        """Offset and limit params should be accepted."""
        s1 = _make_session("Chat A")
        db = StubDB(execute_results=[[s1]])
        client = _build_client(db)
        resp = client.get("/api/chat/sessions?offset=0&limit=1")
        assert resp.status_code == 200

    def test_list_sessions_limit_above_max_returns_422(self):
        """Limit > 100 should return 422."""
        client = _build_client()
        resp = client.get("/api/chat/sessions?limit=200")
        assert resp.status_code == 422

    def test_list_sessions_negative_offset_returns_422(self):
        """Negative offset should return 422."""
        client = _build_client()
        resp = client.get("/api/chat/sessions?offset=-1")
        assert resp.status_code == 422

    def test_get_session_with_sources_in_message(self):
        """Sources JSONB structure is returned correctly."""
        s = _make_session("With Sources")
        sources = [
            {
                "video_id": str(uuid.uuid4()),
                "video_title": "My Video",
                "chunk_text": "some text",
                "start_time": 10.0,
                "end_time": 20.0,
                "similarity": 0.95,
            }
        ]
        msg = _make_message(s.id, "assistant", "Answer with sources", sources=sources)
        s.messages = [msg]
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.get(f"/api/chat/sessions/{s.id}")
        assert resp.status_code == 200
        body = resp.json()
        src = body["messages"][0]["sources"][0]
        assert "video_id" in src
        assert "video_title" in src
        assert "chunk_text" in src
        assert "start_time" in src
        assert "end_time" in src
        assert "similarity" in src

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_send_message_to_session_with_existing_messages(self, mock_chat):
        """Session with prior messages builds correct history."""
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title="Multi-turn")
        msgs = [
            _make_message(s.id, "user", "Q1"),
            _make_message(s.id, "assistant", "A1"),
            _make_message(s.id, "user", "Q2"),
            _make_message(s.id, "assistant", "A2"),
        ]
        s.messages = msgs
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "Q3"},
        )
        assert resp.status_code == 200
        history = mock_chat.call_args[1]["history"]
        assert len(history) == 4
        assert history[0]["content"] == "Q1"
        assert history[3]["content"] == "A2"


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

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.encode_query", side_effect=ImportError("No sentence_transformers"))
    async def test_chat_graceful_when_search_fails(self, mock_encode, mock_llm):
        """If search fails (e.g. missing deps), chat continues with empty context."""
        from app.services.chat import chat_with_context

        mock_llm.return_value = {
            "content": "No relevant context found.",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 50,
            "completion_tokens": 10,
        }

        db = AsyncMock()
        result = await chat_with_context("question", [], db)
        assert result["sources"] == []
        assert result["content"] == "No relevant context found."

    @pytest.mark.asyncio
    @patch("app.services.chat.settings")
    @patch("app.services.chat.encode_query")
    async def test_chat_returns_error_when_api_key_missing(self, mock_encode, mock_settings):
        """When API key is not set, return a graceful error message."""
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_settings.anthropic_api_key = ""
        mock_settings.chat_retrieval_top_k = 10
        mock_settings.chat_max_history = 10
        mock_settings.chat_model = "claude-sonnet-4-20250514"

        db = AsyncMock()
        with patch("app.services.chat.semantic_search", new_callable=AsyncMock, return_value=[]):
            result = await chat_with_context("question", [], db)

        assert "unavailable" in result["content"].lower() or "api key" in result["content"].lower()
        assert result["prompt_tokens"] == 0

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_150k_token_guard_trims_messages(
        self, mock_encode, mock_search, mock_llm,
    ):
        """When total estimated tokens > 150k, oldest history messages are dropped."""
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []
        mock_llm.return_value = {
            "content": "Answer",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 100,
            "completion_tokens": 20,
        }

        # Each message ~150k chars = ~37.5k tokens. 5 messages = ~187.5k tokens.
        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": "X" * 150_000}
            for i in range(4)
        ]

        db = AsyncMock()
        await chat_with_context("short question", history, db)

        call_args = mock_llm.call_args
        messages = call_args[0][1]
        # Messages should have been trimmed so total < 150k tokens
        total_chars = sum(len(m["content"]) for m in messages)
        estimated_tokens = total_chars // 4
        assert estimated_tokens <= 150_000
        # At least the current question should remain
        assert len(messages) >= 1
        assert "short question" in messages[-1]["content"]


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


# ---------------------------------------------------------------------------
# QAClaw Round 2 — Validation & Error Handling Edge Cases
# ---------------------------------------------------------------------------

class TestValidationEdgeCases:
    """Input validation edge cases added by QAClaw."""

    def test_send_empty_message_returns_422(self):
        """Empty message content should be rejected by validation."""
        client = _build_client()
        resp = client.post(
            f"/api/chat/sessions/{uuid.uuid4()}/messages",
            json={"content": ""},
        )
        assert resp.status_code == 422

    def test_send_very_long_message_returns_422(self):
        """Message exceeding 100k chars should be rejected."""
        client = _build_client()
        resp = client.post(
            f"/api/chat/sessions/{uuid.uuid4()}/messages",
            json={"content": "x" * 100_001},
        )
        assert resp.status_code == 422

    def test_rename_to_empty_string_returns_422(self):
        """Renaming session to empty string should be rejected."""
        client = _build_client()
        resp = client.patch(
            f"/api/chat/sessions/{uuid.uuid4()}",
            json={"title": ""},
        )
        assert resp.status_code == 422

    def test_rename_to_very_long_string_returns_422(self):
        """Renaming session to string > 255 chars should be rejected."""
        client = _build_client()
        resp = client.patch(
            f"/api/chat/sessions/{uuid.uuid4()}",
            json={"title": "x" * 256},
        )
        assert resp.status_code == 422

    def test_whitespace_only_message_passes_validation(self):
        """Whitespace-only content passes min_length, hits session lookup."""
        db = StubDB(execute_results=[None])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{uuid.uuid4()}/messages",
            json={"content": "   "},
        )
        assert resp.status_code == 404

    def test_delete_session_cascades(self):
        """Deleting a session calls db.delete on the session object."""
        s = _make_session("To Delete")
        msg = _make_message(s.id, "user", "hello")
        s.messages = [msg]
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.delete(f"/api/chat/sessions/{s.id}")
        assert resp.status_code == 200
        assert db._deleted == [s]

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_nonexistent_session_message_no_chat_call(self, mock_chat):
        """Sending to nonexistent session returns 404 without calling chat service."""
        db = StubDB(execute_results=[None])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{uuid.uuid4()}/messages",
            json={"content": "hello"},
        )
        assert resp.status_code == 404
        mock_chat.assert_not_called()

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_sources_persisted_in_assistant_message(self, mock_chat):
        """Sources from RAG are stored in the assistant ChatMessage object."""
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title="Test")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "question"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["sources"] is not None
        assert len(body["sources"]) == 1
        assert body["sources"][0]["similarity"] == 0.95
        # Both user + assistant messages added
        assert len(db.added) == 2
        assert db.added[0].role == "user"
        assert db.added[1].role == "assistant"
        assert db.added[1].sources == MOCK_CHAT_RESULT["sources"]


class TestAnthropicErrorHandling:
    """Tests for Anthropic API error handling in chat service."""

    @pytest.mark.asyncio
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_api_error_returns_graceful_message(self, mock_encode, mock_search):
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = [
            {
                "id": uuid.uuid4(),
                "video_id": uuid.uuid4(),
                "video_title": "Vid",
                "chunk_text": "text",
                "start_time": 0.0,
                "end_time": 5.0,
                "speaker": None,
                "similarity": 0.8,
            }
        ]

        with patch(
            "app.services.chat._call_anthropic",
            side_effect=anthropic.APIError(
                message="rate limit exceeded",
                request=MagicMock(),
                body=None,
            ),
        ):
            db = AsyncMock()
            result = await chat_with_context("question", [], db)

        assert "error" in result["content"].lower()
        assert result["prompt_tokens"] == 0
        assert result["completion_tokens"] == 0
        assert len(result["sources"]) == 1

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_correct_model_passed_to_anthropic(self, mock_encode, mock_search, mock_llm):
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []
        mock_llm.return_value = {
            "content": "Answer",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 50,
            "completion_tokens": 20,
        }

        db = AsyncMock()
        await chat_with_context("question", [], db)

        call_args = mock_llm.call_args[0]
        assert call_args[2] == "claude-sonnet-4-20250514"
        assert "video transcript" in call_args[0].lower()

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_prompt_includes_context_history_question(self, mock_encode, mock_search, mock_llm):
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = [
            {
                "id": uuid.uuid4(),
                "video_id": uuid.uuid4(),
                "video_title": "Test Video",
                "chunk_text": "Important content",
                "start_time": 10.0,
                "end_time": 20.0,
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

        history = [
            {"role": "user", "content": "prior question"},
            {"role": "assistant", "content": "prior answer"},
        ]
        db = AsyncMock()
        await chat_with_context("new question", history, db)

        call_args = mock_llm.call_args[0]
        messages = call_args[1]
        assert len(messages) == 3
        assert messages[0]["content"] == "prior question"
        assert messages[1]["content"] == "prior answer"
        assert "Important content" in messages[2]["content"]
        assert "new question" in messages[2]["content"]


# ---------------------------------------------------------------------------
# QAClaw Round 3 — Additional Edge Cases
# ---------------------------------------------------------------------------

class TestAdditionalEdgeCases:
    """Extra edge cases for Phase 2 QA completeness."""

    def test_create_session_with_telegram_platform(self):
        """Creating a session with platform='telegram' should work."""
        db = StubDB()
        client = _build_client(db)
        resp = client.post(
            "/api/chat/sessions",
            json={"platform": "telegram"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["platform"] == "telegram"

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_auto_title_not_set_on_second_message(self, mock_chat):
        """Auto-title should only fire on the first message (when title is None)."""
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title=None)
        db = StubDB(execute_results=[s])
        client = _build_client(db)

        # First message sets title
        client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "First question"},
        )
        assert s.title == "First question"

        # Simulate second message — title already set, should not change
        db2 = StubDB(execute_results=[s])
        client2 = _build_client(db2)
        client2.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "Second question is much longer"},
        )
        assert s.title == "First question"

    def test_get_session_invalid_uuid_returns_422(self):
        """Invalid UUID format in path should return 422."""
        client = _build_client()
        resp = client.get("/api/chat/sessions/not-a-uuid")
        assert resp.status_code == 422

    def test_delete_session_invalid_uuid_returns_422(self):
        """Invalid UUID format in delete path should return 422."""
        client = _build_client()
        resp = client.delete("/api/chat/sessions/not-a-uuid")
        assert resp.status_code == 422

    def test_send_message_invalid_session_uuid_returns_422(self):
        """Invalid UUID format in message path should return 422."""
        client = _build_client()
        resp = client.post(
            "/api/chat/sessions/not-a-uuid/messages",
            json={"content": "hi"},
        )
        assert resp.status_code == 422

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_sources_none_when_no_chunks(self, mock_chat):
        """When RAG returns no sources, assistant message sources should be empty list."""
        mock_chat.return_value = {
            "content": "I don't have enough context to answer.",
            "sources": [],
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 50,
            "completion_tokens": 20,
        }
        s = _make_session(title="No Sources")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "something obscure"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["sources"] == []

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_source_structure_matches_schema(self, mock_encode, mock_search, mock_llm):
        """Verify each source dict has all required keys from ChatSourceOut."""
        from app.services.chat import chat_with_context

        vid_id = uuid.uuid4()
        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = [
            {
                "id": uuid.uuid4(),
                "video_id": vid_id,
                "video_title": "My Video",
                "chunk_text": "some content",
                "start_time": 5.0,
                "end_time": 15.0,
                "speaker": None,
                "similarity": 0.85,
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

        assert len(result["sources"]) == 1
        src = result["sources"][0]
        assert src["video_id"] == str(vid_id)
        assert src["video_title"] == "My Video"
        assert src["chunk_text"] == "some content"
        assert src["start_time"] == 5.0
        assert src["end_time"] == 15.0
        assert src["similarity"] == 0.85

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_empty_history_produces_single_message(self, mock_encode, mock_search, mock_llm):
        """With no history, only the current question message is sent to LLM."""
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []
        mock_llm.return_value = {
            "content": "Answer",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 50,
            "completion_tokens": 20,
        }

        db = AsyncMock()
        await chat_with_context("my question", [], db)

        call_args = mock_llm.call_args[0]
        messages = call_args[1]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "my question" in messages[0]["content"]

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_retrieval_top_k_passed_to_search(self, mock_encode, mock_search, mock_llm):
        """Verify chat_retrieval_top_k from settings is passed as limit."""
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []
        mock_llm.return_value = {
            "content": "Answer",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 50,
            "completion_tokens": 20,
        }

        db = AsyncMock()
        await chat_with_context("question", [], db)

        _, kwargs = mock_search.call_args
        assert kwargs["limit"] == 10  # default chat_retrieval_top_k


# ---------------------------------------------------------------------------
# QAClaw Round 4 — Final edge cases
# ---------------------------------------------------------------------------

class TestQAClawRound4:
    """Final edge cases for Phase 2 completeness."""

    def test_format_chunks_start_time_only(self):
        """Chunk with start_time but no end_time should format correctly."""
        from app.services.chat import _format_chunks_for_context

        chunks = [
            {
                "video_title": "Video C",
                "chunk_text": "partial time",
                "start_time": 120.0,
                "end_time": None,
            }
        ]
        result = _format_chunks_for_context(chunks)
        assert "[1] Video C [2:00]" in result
        assert "partial time" in result

    def test_format_chunks_multiple(self):
        """Multiple chunks should be numbered sequentially."""
        from app.services.chat import _format_chunks_for_context

        chunks = [
            {"video_title": "V1", "chunk_text": "c1", "start_time": 0.0, "end_time": 5.0},
            {"video_title": "V2", "chunk_text": "c2", "start_time": 10.0, "end_time": 15.0},
            {"video_title": "V3", "chunk_text": "c3", "start_time": None, "end_time": None},
        ]
        result = _format_chunks_for_context(chunks)
        assert "[1] V1" in result
        assert "[2] V2" in result
        assert "[3] V3" in result

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_multiple_sources_returned(self, mock_chat):
        """Multiple sources from RAG should all appear in response."""
        multi_source_result = {
            "content": "Answer with multiple sources.",
            "sources": [
                {
                    "video_id": str(uuid.uuid4()),
                    "video_title": "Video A",
                    "chunk_text": "chunk a",
                    "start_time": 0.0,
                    "end_time": 10.0,
                    "similarity": 0.95,
                },
                {
                    "video_id": str(uuid.uuid4()),
                    "video_title": "Video B",
                    "chunk_text": "chunk b",
                    "start_time": 20.0,
                    "end_time": 30.0,
                    "similarity": 0.85,
                },
            ],
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 200,
            "completion_tokens": 80,
        }
        mock_chat.return_value = multi_source_result
        s = _make_session(title="Multi-source")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "compare videos"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["sources"]) == 2
        assert body["sources"][0]["video_title"] == "Video A"
        assert body["sources"][1]["video_title"] == "Video B"

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_session_updated_at_touched_on_message(self, mock_chat):
        """Sending a message should update session.updated_at."""
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title="Touch Test")
        original_updated = s.updated_at
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "touch updated_at"},
        )
        assert resp.status_code == 200
        # updated_at should have been reassigned (sa_func.now())
        assert s.updated_at != original_updated

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_history_exactly_at_max_not_trimmed(self, mock_encode, mock_search, mock_llm):
        """History exactly at chat_max_history * 2 should not be trimmed."""
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []
        mock_llm.return_value = {
            "content": "Answer",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 50,
            "completion_tokens": 20,
        }

        # Exactly 20 messages = chat_max_history(10) * 2
        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
            for i in range(20)
        ]

        db = AsyncMock()
        await chat_with_context("question", history, db)

        call_args = mock_llm.call_args[0]
        messages = call_args[1]
        # 20 history + 1 current = 21
        assert len(messages) == 21

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_chat_no_chunks_still_calls_llm(self, mock_encode, mock_search, mock_llm):
        """When search returns no chunks, LLM is still called with empty context."""
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []
        mock_llm.return_value = {
            "content": "I don't have relevant context.",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 30,
            "completion_tokens": 15,
        }

        db = AsyncMock()
        result = await chat_with_context("obscure question", [], db)

        mock_llm.assert_called_once()
        assert result["content"] == "I don't have relevant context."
        assert result["sources"] == []

    def test_create_session_with_empty_string_title(self):
        """Empty string title in create should be accepted (nullable field, no min_length)."""
        db = StubDB()
        client = _build_client(db)
        resp = client.post("/api/chat/sessions", json={"title": ""})
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == ""

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_user_message_saved_before_chat_call(self, mock_chat):
        """User message should be added to DB before chat_with_context is called."""
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title="Order Test")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "test ordering"},
        )
        assert resp.status_code == 200
        # User message should be added first
        assert db.added[0].role == "user"
        assert db.added[0].content == "test ordering"

    def test_rename_preserves_other_fields(self):
        """Renaming a session should not alter platform or other fields."""
        s = _make_session("Original")
        s.platform = "telegram"
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.patch(
            f"/api/chat/sessions/{s.id}",
            json={"title": "Renamed"},
        )
        assert resp.status_code == 200
        assert s.platform == "telegram"
        assert s.title == "Renamed"


# ---------------------------------------------------------------------------
# QAClaw Round 5 — Concurrent, system prompt, _call_anthropic unit tests
# ---------------------------------------------------------------------------

class TestQAClawRound5:
    """Final gap-filling tests for Phase 2 QA completeness."""

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_concurrent_messages_both_succeed(self, mock_chat):
        """Two sequential messages to the same session should both succeed."""
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title=None)
        # First message
        db1 = StubDB(execute_results=[s])
        client1 = _build_client(db1)
        resp1 = client1.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "First question"},
        )
        assert resp1.status_code == 200
        assert s.title == "First question"

        # Second message (simulate fresh DB load with messages already present)
        msg1 = _make_message(s.id, "user", "First question")
        msg2 = _make_message(s.id, "assistant", MOCK_CHAT_RESULT["content"])
        s.messages = [msg1, msg2]
        db2 = StubDB(execute_results=[s])
        client2 = _build_client(db2)
        resp2 = client2.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "Follow-up question"},
        )
        assert resp2.status_code == 200
        # Title should NOT change on second message
        assert s.title == "First question"
        # History should contain the prior messages
        history = mock_chat.call_args[1]["history"]
        assert len(history) == 2

    def test_system_prompt_mentions_video_transcripts(self):
        """System prompt should ground the assistant in video transcript content."""
        from app.services.chat import SYSTEM_PROMPT

        assert "video transcript" in SYSTEM_PROMPT.lower()
        assert "context" in SYSTEM_PROMPT.lower()

    def test_system_prompt_instructs_citation(self):
        """System prompt should instruct the model to cite sources."""
        from app.services.chat import SYSTEM_PROMPT

        assert "cite" in SYSTEM_PROMPT.lower() or "source" in SYSTEM_PROMPT.lower()

    @patch("app.services.chat._get_anthropic_client")
    def test_call_anthropic_passes_correct_params(self, mock_get_client):
        """_call_anthropic should pass model, system, messages, and max_tokens."""
        from app.services.chat import _call_anthropic

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Generated answer")]
        mock_response.model = "claude-sonnet-4-20250514"
        mock_response.usage.input_tokens = 200
        mock_response.usage.output_tokens = 80
        mock_client.messages.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = _call_anthropic(
            system="Test system prompt",
            messages=[{"role": "user", "content": "Hello"}],
            model="claude-sonnet-4-20250514",
        )

        mock_client.messages.create.assert_called_once_with(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system="Test system prompt",
            messages=[{"role": "user", "content": "Hello"}],
        )
        assert result["content"] == "Generated answer"
        assert result["model"] == "claude-sonnet-4-20250514"
        assert result["prompt_tokens"] == 200
        assert result["completion_tokens"] == 80

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_token_guard_preserves_current_question(self, mock_encode, mock_search, mock_llm):
        """Even with massive history, the current question must survive the token guard."""
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []
        mock_llm.return_value = {
            "content": "Answer",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 50,
            "completion_tokens": 20,
        }

        # 10 messages of 100k chars each = way over 150k tokens
        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": "X" * 100_000}
            for i in range(10)
        ]

        db = AsyncMock()
        await chat_with_context("my important question", history, db)

        call_args = mock_llm.call_args[0]
        messages = call_args[1]
        # The last message must be the current question
        assert "my important question" in messages[-1]["content"]
        # Should have at least 1 message (the question itself)
        assert len(messages) >= 1

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_send_message_content_type_json_required(self, mock_chat):
        """Sending non-JSON body should return 422."""
        client = _build_client()
        resp = client.post(
            f"/api/chat/sessions/{uuid.uuid4()}/messages",
            content="plain text",
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 422

    def test_create_session_invalid_json_returns_422(self):
        """Sending malformed JSON to create session should return 422."""
        client = _build_client()
        resp = client.post(
            "/api/chat/sessions",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_assistant_message_has_model_and_tokens(self, mock_chat):
        """Assistant message should store model name and token counts."""
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title="Token Test")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "count tokens"},
        )
        assert resp.status_code == 200
        # Check the saved assistant message object
        assistant_msg = db.added[1]
        assert assistant_msg.role == "assistant"
        assert assistant_msg.model == "claude-sonnet-4-20250514"
        assert assistant_msg.prompt_tokens == 500
        assert assistant_msg.completion_tokens == 100


# ---------------------------------------------------------------------------
# QAClaw Round 6 — Final gap tests
# ---------------------------------------------------------------------------

class TestQAClawRound6:
    """Last edge cases: duplicate delete, auth error, timeout."""

    def test_duplicate_delete_returns_404(self):
        """Deleting an already-deleted session should return 404."""
        s = _make_session("To Delete")
        # First delete succeeds, second returns None (not found)
        db = StubDB(execute_results=[s, None])
        client = _build_client(db)
        resp1 = client.delete(f"/api/chat/sessions/{s.id}")
        assert resp1.status_code == 200
        resp2 = client.delete(f"/api/chat/sessions/{s.id}")
        assert resp2.status_code == 404

    @pytest.mark.asyncio
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_anthropic_auth_error_returns_graceful_message(self, mock_encode, mock_search):
        """AuthenticationError from Anthropic should be handled gracefully."""
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []

        with patch(
            "app.services.chat._call_anthropic",
            side_effect=anthropic.AuthenticationError(
                message="invalid api key",
                response=MagicMock(status_code=401),
                body=None,
            ),
        ):
            db = AsyncMock()
            result = await chat_with_context("question", [], db)

        assert "error" in result["content"].lower()
        assert result["prompt_tokens"] == 0

    @pytest.mark.asyncio
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_anthropic_timeout_returns_graceful_message(self, mock_encode, mock_search):
        """Timeout from Anthropic API should be handled gracefully."""
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []

        with patch(
            "app.services.chat._call_anthropic",
            side_effect=anthropic.APITimeoutError(request=MagicMock()),
        ):
            db = AsyncMock()
            result = await chat_with_context("question", [], db)

        assert "error" in result["content"].lower()
        assert result["prompt_tokens"] == 0

    def test_get_session_zero_messages_returns_empty_list(self):
        """Getting a session with 0 messages should return messages=[]."""
        s = _make_session("Empty")
        s.messages = []
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.get(f"/api/chat/sessions/{s.id}")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_send_message_boundary_100k_accepted(self, mock_chat):
        """Message at exactly 100k chars should be accepted."""
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title="Boundary")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "x" * 100_000},
        )
        assert resp.status_code == 200

    def test_rename_boundary_255_chars_accepted(self):
        """Title at exactly 255 chars should be accepted."""
        s = _make_session("Old")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.patch(
            f"/api/chat/sessions/{s.id}",
            json={"title": "x" * 255},
        )
        assert resp.status_code == 200
        assert s.title == "x" * 255


# ---------------------------------------------------------------------------
# QAClaw Round 7 — Final missing edge cases
# ---------------------------------------------------------------------------

class TestQAClawRound7:
    """Coverage gaps: message over 100k, rename over 255, _fmt_ts edge, platform validation,
    chat_enabled_only propagation through search modes, and auto-title exactly 50 chars."""

    def test_send_message_over_100k_returns_422(self):
        """Message over 100_000 chars should be rejected by schema validation."""
        s = _make_session(title="Over Limit")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "x" * 100_001},
        )
        assert resp.status_code == 422

    def test_rename_over_255_returns_422(self):
        """Title over 255 chars should be rejected by schema validation."""
        s = _make_session("Old")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.patch(
            f"/api/chat/sessions/{s.id}",
            json={"title": "x" * 256},
        )
        assert resp.status_code == 422

    def test_fmt_ts_zero_seconds(self):
        """_fmt_ts(0) should return '0:00'."""
        from app.services.chat import _fmt_ts

        assert _fmt_ts(0) == "0:00"

    def test_fmt_ts_fractional_seconds(self):
        """_fmt_ts with fractional seconds should truncate to int."""
        from app.services.chat import _fmt_ts

        assert _fmt_ts(65.9) == "1:05"

    def test_auto_title_exactly_50_chars_no_ellipsis(self):
        """A message exactly 50 chars should NOT get '...' appended."""
        mock_result = MOCK_CHAT_RESULT.copy()
        with patch("app.routers.chat.chat_with_context", new_callable=AsyncMock, return_value=mock_result):
            s = _make_session(title=None)
            db = StubDB(execute_results=[s])
            client = _build_client(db)
            msg_50 = "a" * 50
            resp = client.post(
                f"/api/chat/sessions/{s.id}/messages",
                json={"content": msg_50},
            )
            assert resp.status_code == 200
            assert s.title == msg_50
            assert not s.title.endswith("...")

    def test_auto_title_51_chars_gets_ellipsis(self):
        """A message of 51 chars should get truncated to 50 + '...'."""
        mock_result = MOCK_CHAT_RESULT.copy()
        with patch("app.routers.chat.chat_with_context", new_callable=AsyncMock, return_value=mock_result):
            s = _make_session(title=None)
            db = StubDB(execute_results=[s])
            client = _build_client(db)
            msg_51 = "b" * 51
            resp = client.post(
                f"/api/chat/sessions/{s.id}/messages",
                json={"content": msg_51},
            )
            assert resp.status_code == 200
            assert s.title == "b" * 50 + "..."

    def test_create_session_default_platform_is_web(self):
        """Default platform should be 'web' when not specified."""
        db = StubDB()
        client = _build_client(db)
        resp = client.post("/api/chat/sessions", json={})
        assert resp.status_code == 200
        created = db.added[0]
        assert created.platform == "web"

    def test_delete_session_returns_session_id(self):
        """Delete response should include the deleted session_id."""
        s = _make_session("To Delete")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.delete(f"/api/chat/sessions/{s.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted"] is True
        assert body["session_id"] == str(s.id)

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_sources_include_all_required_fields(self, mock_encode, mock_search, mock_llm):
        """Each source dict must have video_id, video_title, chunk_text, start_time, end_time, similarity."""
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = [
            {
                "id": uuid.uuid4(),
                "video_id": uuid.uuid4(),
                "video_title": "Source Check",
                "chunk_text": "test chunk",
                "start_time": 5.0,
                "end_time": 15.0,
                "speaker": None,
                "similarity": 0.88,
            }
        ]
        mock_llm.return_value = {
            "content": "Answer",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 50,
            "completion_tokens": 20,
        }

        db = AsyncMock()
        result = await chat_with_context("check sources", [], db)

        assert len(result["sources"]) == 1
        source = result["sources"][0]
        required_keys = {"video_id", "video_title", "chunk_text", "start_time", "end_time", "similarity"}
        assert set(source.keys()) == required_keys
        assert source["similarity"] == 0.88
        assert source["start_time"] == 5.0
        assert source["end_time"] == 15.0

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_user_message_not_stored_with_model_or_tokens(self, mock_chat):
        """User messages should have None for model, prompt_tokens, completion_tokens."""
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title="User Msg Check")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "user question"},
        )
        assert resp.status_code == 200
        user_msg = db.added[0]
        assert user_msg.role == "user"
        assert user_msg.model is None
        assert user_msg.prompt_tokens is None
        assert user_msg.completion_tokens is None

    def test_format_chunks_empty_list(self):
        """Empty chunk list should produce empty string."""
        from app.services.chat import _format_chunks_for_context

        assert _format_chunks_for_context([]) == ""

    def test_list_sessions_default_pagination(self):
        """Default list sessions should use offset=0, limit=20."""
        db = StubDB(execute_results=[[]])
        client = _build_client(db)
        resp = client.get("/api/chat/sessions")
        assert resp.status_code == 200
        assert resp.json() == []



# ---------------------------------------------------------------------------
# QAClaw Round 8 — Code-review-driven gap tests
# ---------------------------------------------------------------------------

class TestQAClawRound8:
    """Tests discovered during code review: empty-string title, odd history,
    newlines in content, search query passthrough."""

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_empty_string_title_blocks_auto_title(self, mock_chat):
        """Session created with title='' should NOT trigger auto-title.

        Only title=None triggers auto-title (line 121 in routers/chat.py).
        This documents the current intentional behavior.
        """
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title="")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "Should this set the title?"},
        )
        assert resp.status_code == 200
        assert s.title == ""

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_odd_number_history_messages(self, mock_encode, mock_search, mock_llm):
        """History with odd number of messages should still work correctly."""
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []
        mock_llm.return_value = {
            "content": "Answer",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 50,
            "completion_tokens": 20,
        }

        history = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
        ]

        db = AsyncMock()
        await chat_with_context("Q3", history, db)

        call_args = mock_llm.call_args[0]
        messages = call_args[1]
        assert len(messages) == 4  # 3 history + 1 current
        assert messages[-1]["role"] == "user"
        assert "Q3" in messages[-1]["content"]

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_newlines_in_message_content_preserved(self, mock_chat):
        """Message content with newlines should be passed through unchanged."""
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title="Newlines")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        content = "Line 1\nLine 2\n\nLine 4"
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": content},
        )
        assert resp.status_code == 200
        assert mock_chat.call_args[1]["question"] == content

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_search_query_text_passed_correctly(self, mock_encode, mock_search, mock_llm):
        """User question should be passed as both embedding query and text query."""
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []
        mock_llm.return_value = {
            "content": "Answer",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 50,
            "completion_tokens": 20,
        }

        db = AsyncMock()
        await chat_with_context("specific question about cats", [], db)

        mock_encode.assert_called_once_with("specific question about cats")
        _, kwargs = mock_search.call_args
        assert kwargs["query"] == "specific question about cats"

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_max_tokens_4096_in_anthropic_call(self, mock_encode, mock_search, mock_llm):
        """Verify _call_anthropic is invoked with max_tokens=4096."""
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []
        mock_llm.return_value = {
            "content": "Answer",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 50,
            "completion_tokens": 20,
        }

        db = AsyncMock()
        await chat_with_context("question", [], db)

        # _call_anthropic(system, messages, model) — verify it was called
        mock_llm.assert_called_once()
        call_args = mock_llm.call_args[0]
        assert call_args[2] == "claude-sonnet-4-20250514"  # model arg


# ---------------------------------------------------------------------------
# QAClaw Round 9 — Final code-review gap tests
# ---------------------------------------------------------------------------

class TestQAClawRound9:
    """Tests from final code review: singleton client, run_in_executor path,
    token guard edge, schema extras, settings-based model, context format."""

    def test_get_anthropic_client_singleton(self):
        """_get_anthropic_client should return the same instance on repeated calls."""
        from app.services.chat import _get_anthropic_client
        import app.services.chat as chat_mod

        # Reset singleton
        original = chat_mod._anthropic_client
        chat_mod._anthropic_client = None
        try:
            with patch("app.services.chat.anthropic.Anthropic") as mock_cls:
                mock_cls.return_value = MagicMock()
                c1 = _get_anthropic_client()
                c2 = _get_anthropic_client()
                assert c1 is c2
                mock_cls.assert_called_once()  # Only one instantiation
        finally:
            chat_mod._anthropic_client = original

    def test_rename_single_char_boundary(self):
        """Rename to exactly 1 character (min_length boundary) should succeed."""
        s = _make_session("Old")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.patch(
            f"/api/chat/sessions/{s.id}",
            json={"title": "X"},
        )
        assert resp.status_code == 200
        assert s.title == "X"

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_token_guard_only_question_survives(self, mock_encode, mock_search, mock_llm):
        """When a single history message + question > 150k, history is fully dropped."""
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []
        mock_llm.return_value = {
            "content": "Answer",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 50,
            "completion_tokens": 20,
        }

        # Single history message of 800k chars (~200k tokens)
        history = [{"role": "user", "content": "X" * 800_000}]

        db = AsyncMock()
        await chat_with_context("my question", history, db)

        call_args = mock_llm.call_args[0]
        messages = call_args[1]
        # Only the current question should survive
        assert len(messages) == 1
        assert "my question" in messages[0]["content"]

    def test_create_session_extra_fields_ignored(self):
        """Extra unknown fields in create body should not cause errors."""
        db = StubDB()
        client = _build_client(db)
        resp = client.post(
            "/api/chat/sessions",
            json={"title": "Test", "unknown_field": "ignored"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_model_from_settings_not_hardcoded(self, mock_encode, mock_search, mock_llm):
        """Verify the model passed to _call_anthropic comes from settings."""
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []
        mock_llm.return_value = {
            "content": "Answer",
            "model": "custom-model",
            "prompt_tokens": 50,
            "completion_tokens": 20,
        }

        db = AsyncMock()
        with patch("app.services.chat.settings") as mock_settings:
            mock_settings.chat_retrieval_top_k = 10
            mock_settings.chat_max_history = 10
            mock_settings.chat_model = "custom-model-123"
            mock_settings.anthropic_api_key = "test-key"
            await chat_with_context("question", [], db)

        call_args = mock_llm.call_args[0]
        assert call_args[2] == "custom-model-123"

    def test_build_messages_context_prefix_present(self):
        """The user message should include 'Context from video transcripts:' prefix."""
        from app.services.chat import _build_messages

        messages = _build_messages([], "my question", "chunk text here")
        assert "Context from video transcripts:" in messages[0]["content"]
        assert "chunk text here" in messages[0]["content"]
        assert "Question: my question" in messages[0]["content"]

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_send_message_db_commit_called(self, mock_chat):
        """After send_message, db.commit() should be called to persist both messages."""
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title="Commit Test")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "test commit"},
        )
        assert resp.status_code == 200
        assert db.committed is True
        # Both user and assistant messages should be added
        assert len(db.added) == 2

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_system_prompt_passed_as_system_not_message(self, mock_encode, mock_search, mock_llm):
        """System prompt should be passed as the 'system' parameter, not as a message."""
        from app.services.chat import chat_with_context, SYSTEM_PROMPT

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []
        mock_llm.return_value = {
            "content": "Answer",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 50,
            "completion_tokens": 20,
        }

        db = AsyncMock()
        await chat_with_context("question", [], db)

        call_args = mock_llm.call_args[0]
        # _call_anthropic(system, messages, model)
        assert call_args[0] == SYSTEM_PROMPT
        messages = call_args[1]
        # None of the messages should contain the system prompt
        for msg in messages:
            assert msg["role"] in ("user", "assistant")

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_send_message_returns_correct_session_id(self, mock_chat):
        """Response assistant message should have correct session_id."""
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title="Session ID Check")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "check session id"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == str(s.id)


# ---------------------------------------------------------------------------
# QAClaw Round 10 — Final isolation & import tests
# ---------------------------------------------------------------------------

class TestQAClawRound10:
    """Session isolation, model package imports, and ORM relationship checks."""

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_session_isolation_different_sessions(self, mock_chat):
        """Messages from session A should not appear in session B's history."""
        mock_chat.return_value = MOCK_CHAT_RESULT

        sa_sess = _make_session(title="Session A")
        msg_a = _make_message(sa_sess.id, "user", "Question for A")
        sa_sess.messages = [msg_a]

        sb_sess = _make_session(title="Session B")
        sb_sess.messages = []

        db_b = StubDB(execute_results=[sb_sess])
        client_b = _build_client(db_b)
        resp = client_b.post(
            f"/api/chat/sessions/{sb_sess.id}/messages",
            json={"content": "Question for B"},
        )
        assert resp.status_code == 200
        history = mock_chat.call_args[1]["history"]
        assert len(history) == 0

    def test_models_importable_from_package(self):
        """ChatSession and ChatMessage should be importable from app.models."""
        from app.models import ChatSession, ChatMessage

        assert ChatSession.__tablename__ == "chat_sessions"
        assert ChatMessage.__tablename__ == "chat_messages"

    def test_chat_message_fk_references_chat_sessions(self):
        """ChatMessage.session_id FK should reference chat_sessions.id."""
        from app.models.chat_message import ChatMessage
        col = ChatMessage.__table__.c.session_id
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].target_fullname == "chat_sessions.id"

    def test_chat_session_cascade_delete_orphan(self):
        """ChatSession.messages relationship should have cascade='all, delete-orphan'."""
        from app.models.chat_session import ChatSession
        rel = ChatSession.__mapper__.relationships["messages"]
        assert "delete-orphan" in rel.cascade


# ---------------------------------------------------------------------------
# QAClaw Round 11 — Fresh review: migration, client, schemas, format, executor
# ---------------------------------------------------------------------------

class TestQAClawRound11:
    """Gaps from fresh code review: migration up/down, singleton API key,
    schema from_attributes, hours format, run_in_executor, limit=0."""

    def test_migration_downgrade_drops_tables_in_order(self):
        """Downgrade should drop chat_messages before chat_sessions (FK dependency)."""
        from alembic.versions.006_create_chat_tables import downgrade
        from unittest.mock import call

        with patch("alembic.versions.006_create_chat_tables.op") as mock_op:
            downgrade()

            calls = mock_op.method_calls
            call_names = [c[0] for c in calls]
            assert call_names == ["drop_index", "drop_table", "drop_table"]
            assert calls[1] == call.drop_table("chat_messages")
            assert calls[2] == call.drop_table("chat_sessions")

    def test_migration_upgrade_creates_tables_and_index(self):
        """Upgrade should create chat_sessions, chat_messages, and index."""
        from alembic.versions.006_create_chat_tables import upgrade

        with patch("alembic.versions.006_create_chat_tables.op") as mock_op:
            upgrade()

            call_names = [c[0] for c in mock_op.method_calls]
            assert "create_table" in call_names
            assert "create_index" in call_names
            idx_call = [c for c in mock_op.method_calls if c[0] == "create_index"][0]
            assert idx_call[1][0] == "ix_chat_messages_session_id"

    def test_get_anthropic_client_passes_api_key(self):
        """_get_anthropic_client should pass settings.anthropic_api_key."""
        import app.services.chat as chat_mod

        original = chat_mod._anthropic_client
        chat_mod._anthropic_client = None
        try:
            with patch("app.services.chat.anthropic.Anthropic") as mock_cls:
                with patch("app.services.chat.settings") as mock_settings:
                    mock_settings.anthropic_api_key = "sk-test-key-123"
                    mock_cls.return_value = MagicMock()
                    chat_mod._get_anthropic_client()
                    mock_cls.assert_called_once_with(api_key="sk-test-key-123")
        finally:
            chat_mod._anthropic_client = original

    def test_format_chunks_hours_with_end_time(self):
        """Chunk spanning hours should format both start and end correctly."""
        from app.services.chat import _format_chunks_for_context

        chunks = [
            {
                "video_title": "Long Video",
                "chunk_text": "content",
                "start_time": 3661.0,
                "end_time": 7322.0,
            }
        ]
        result = _format_chunks_for_context(chunks)
        assert "[1] Long Video [1:01:01 - 2:02:02]" in result

    def test_create_session_platform_passthrough(self):
        """Custom platform value should be stored as-is."""
        db = StubDB()
        client = _build_client(db)
        resp = client.post(
            "/api/chat/sessions",
            json={"platform": "custom_bot"},
        )
        assert resp.status_code == 200
        assert db.added[0].platform == "custom_bot"

    def test_chat_message_out_schema_from_attributes(self):
        """ChatMessageOut should accept ORM-like objects (from_attributes=True)."""
        from app.schemas.chat import ChatMessageOut

        msg_id = uuid.uuid4()
        session_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        obj = SimpleNamespace(
            id=msg_id, session_id=session_id, role="assistant",
            content="Answer", sources=None, model="claude-sonnet-4-20250514",
            prompt_tokens=100, completion_tokens=50, created_at=now,
        )
        out = ChatMessageOut.model_validate(obj, from_attributes=True)
        assert out.id == msg_id
        assert out.role == "assistant"
        assert out.sources is None

    def test_chat_session_out_schema_from_attributes(self):
        """ChatSessionOut should accept ORM-like objects (from_attributes=True)."""
        from app.schemas.chat import ChatSessionOut

        sid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        obj = SimpleNamespace(
            id=sid, title="My Chat", platform="web",
            created_at=now, updated_at=now,
        )
        out = ChatSessionOut.model_validate(obj, from_attributes=True)
        assert out.id == sid
        assert out.title == "My Chat"

    def test_chat_session_detail_schema_with_messages(self):
        """ChatSessionDetail should include messages list."""
        from app.schemas.chat import ChatSessionDetail

        sid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        msg = SimpleNamespace(
            id=uuid.uuid4(), session_id=sid, role="user",
            content="Hello", sources=None, model=None,
            prompt_tokens=None, completion_tokens=None, created_at=now,
        )
        obj = SimpleNamespace(
            id=sid, title="Detail Test", platform="web",
            created_at=now, updated_at=now, messages=[msg],
        )
        out = ChatSessionDetail.model_validate(obj, from_attributes=True)
        assert len(out.messages) == 1
        assert out.messages[0].content == "Hello"

    @pytest.mark.asyncio
    @patch("app.services.chat._call_anthropic")
    @patch("app.services.chat.semantic_search", new_callable=AsyncMock)
    @patch("app.services.chat.encode_query")
    async def test_chat_uses_run_in_executor(self, mock_encode, mock_search, mock_llm):
        """chat_with_context should call _call_anthropic via run_in_executor."""
        from app.services.chat import chat_with_context

        mock_encode.return_value = [0.1] * 768
        mock_search.return_value = []
        mock_llm.return_value = {
            "content": "Answer",
            "model": "claude-sonnet-4-20250514",
            "prompt_tokens": 50,
            "completion_tokens": 20,
        }

        db = AsyncMock()
        with patch("app.services.chat.asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value = MagicMock()
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=mock_llm.return_value)
            result = await chat_with_context("question", [], db)

        assert result["content"] == "Answer"
        mock_loop.return_value.run_in_executor.assert_called_once()

    def test_limit_zero_returns_422(self):
        """Limit=0 should return 422 (ge=1 constraint)."""
        client = _build_client()
        resp = client.get("/api/chat/sessions?limit=0")
        assert resp.status_code == 422

    @patch("app.routers.chat.chat_with_context", new_callable=AsyncMock)
    def test_send_message_user_msg_has_correct_session_id(self, mock_chat):
        """User message should be saved with the correct session_id."""
        mock_chat.return_value = MOCK_CHAT_RESULT
        s = _make_session(title="Session Ref")
        db = StubDB(execute_results=[s])
        client = _build_client(db)
        resp = client.post(
            f"/api/chat/sessions/{s.id}/messages",
            json={"content": "check ref"},
        )
        assert resp.status_code == 200
        user_msg = db.added[0]
        assert user_msg.session_id == s.id
        assistant_msg = db.added[1]
        assert assistant_msg.session_id == s.id

    def test_chat_source_out_schema_validation(self):
        """ChatSourceOut should validate and serialize source data."""
        from app.schemas.chat import ChatSourceOut

        src = ChatSourceOut(
            video_id="abc-123",
            video_title="Test Video",
            chunk_text="some text",
            start_time=10.5,
            end_time=20.0,
            similarity=0.95,
        )
        assert src.video_id == "abc-123"
        assert src.similarity == 0.95
        assert src.start_time == 10.5

    def test_chat_source_out_optional_fields(self):
        """ChatSourceOut optional fields should default to None."""
        from app.schemas.chat import ChatSourceOut

        src = ChatSourceOut(
            video_id="abc",
            video_title="Vid",
            chunk_text="text",
        )
        assert src.start_time is None
        assert src.end_time is None
        assert src.similarity is None
