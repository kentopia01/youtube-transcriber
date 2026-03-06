"""Tests for Phase 1: Chat toggle system (API + search filter)."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.dependencies import get_db
from app.main import create_app
from app.services.search import _build_where_clause, semantic_search


# ---------------------------------------------------------------------------
# DB helpers (reuse pattern from test_api_endpoints)
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
    def __init__(self, execute_results=None, scalar_value=0):
        self._results = list(execute_results or [])
        self._scalar = scalar_value
        self.added = []
        self.committed = False
        self._exec_idx = 0

    async def execute(self, *args, **kwargs):
        if self._exec_idx < len(self._results):
            val = self._results[self._exec_idx]
            self._exec_idx += 1
            return _FakeResult(val)
        return _FakeResult(None)

    async def scalar(self, *args, **kwargs):
        return self._scalar

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if hasattr(obj, "id") and obj.id is None:
                obj.id = uuid.uuid4()

    async def commit(self):
        self.committed = True


def _build_client(db=None):
    from fastapi.testclient import TestClient

    app = create_app()

    async def _override():
        yield db or StubDB()

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


# ---------------------------------------------------------------------------
# Video chat toggle
# ---------------------------------------------------------------------------

class TestVideoChatToggle:
    def test_toggle_video_on(self):
        video = SimpleNamespace(
            id=uuid.uuid4(), chat_enabled=False, title="Test",
        )
        db = StubDB(execute_results=[video])
        client = _build_client(db)
        resp = client.patch(
            f"/api/videos/{video.id}/chat-toggle",
            json={"enabled": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["chat_enabled"] is True
        assert video.chat_enabled is True

    def test_toggle_video_off(self):
        video = SimpleNamespace(
            id=uuid.uuid4(), chat_enabled=True, title="Test",
        )
        db = StubDB(execute_results=[video])
        client = _build_client(db)
        resp = client.patch(
            f"/api/videos/{video.id}/chat-toggle",
            json={"enabled": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["chat_enabled"] is False
        assert video.chat_enabled is False

    def test_toggle_nonexistent_video_returns_404(self):
        db = StubDB(execute_results=[None])
        client = _build_client(db)
        resp = client.patch(
            f"/api/videos/{uuid.uuid4()}/chat-toggle",
            json={"enabled": True},
        )
        assert resp.status_code == 404

    def test_toggle_missing_body_returns_422(self):
        client = _build_client()
        resp = client.patch(
            f"/api/videos/{uuid.uuid4()}/chat-toggle",
            json={},
        )
        assert resp.status_code == 422

    def test_toggle_invalid_enabled_value_returns_422(self):
        client = _build_client()
        resp = client.patch(
            f"/api/videos/{uuid.uuid4()}/chat-toggle",
            json={"enabled": "notabool"},
        )
        assert resp.status_code == 422

    def test_toggle_invalid_uuid_returns_422(self):
        client = _build_client()
        resp = client.patch(
            "/api/videos/not-a-uuid/chat-toggle",
            json={"enabled": True},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Channel chat toggle (bulk updates videos)
# ---------------------------------------------------------------------------

class TestChannelChatToggle:
    def test_toggle_channel_updates_all_videos(self):
        channel = SimpleNamespace(
            id=uuid.uuid4(), chat_enabled=True, name="Test Channel",
        )
        video1 = SimpleNamespace(id=uuid.uuid4(), chat_enabled=True, channel_id=channel.id)
        video2 = SimpleNamespace(id=uuid.uuid4(), chat_enabled=True, channel_id=channel.id)
        # First execute returns channel, second returns videos list
        db = StubDB(execute_results=[channel, [video1, video2]])
        client = _build_client(db)
        resp = client.patch(
            f"/api/channels/{channel.id}/chat-toggle",
            json={"enabled": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["chat_enabled"] is False
        assert body["videos_updated"] == 2
        assert channel.chat_enabled is False
        assert video1.chat_enabled is False
        assert video2.chat_enabled is False

    def test_toggle_channel_on(self):
        channel = SimpleNamespace(
            id=uuid.uuid4(), chat_enabled=False, name="Test Channel",
        )
        db = StubDB(execute_results=[channel, []])
        client = _build_client(db)
        resp = client.patch(
            f"/api/channels/{channel.id}/chat-toggle",
            json={"enabled": True},
        )
        assert resp.status_code == 200
        assert resp.json()["chat_enabled"] is True
        assert channel.chat_enabled is True

    def test_toggle_nonexistent_channel_returns_404(self):
        db = StubDB(execute_results=[None])
        client = _build_client(db)
        resp = client.patch(
            f"/api/channels/{uuid.uuid4()}/chat-toggle",
            json={"enabled": False},
        )
        assert resp.status_code == 404

    def test_toggle_channel_missing_body_returns_422(self):
        client = _build_client()
        resp = client.patch(
            f"/api/channels/{uuid.uuid4()}/chat-toggle",
            json={},
        )
        assert resp.status_code == 422

    def test_toggle_channel_zero_videos(self):
        """Channel with 0 videos — toggle should succeed without error."""
        channel = SimpleNamespace(
            id=uuid.uuid4(), chat_enabled=True, name="Empty Channel",
        )
        db = StubDB(execute_results=[channel, []])
        client = _build_client(db)
        resp = client.patch(
            f"/api/channels/{channel.id}/chat-toggle",
            json={"enabled": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["chat_enabled"] is False
        assert body["videos_updated"] == 0
        assert channel.chat_enabled is False


# ---------------------------------------------------------------------------
# Search with chat_enabled_only filter
# ---------------------------------------------------------------------------

FAKE_EMBEDDING = [0.1] * 768


class TestBuildWhereClauseChatEnabled:
    def test_chat_enabled_only_adds_filter(self):
        clause, params = _build_where_clause(None, chat_enabled_only=True)
        assert "chat_enabled" in clause
        assert "WHERE" in clause

    def test_channel_and_chat_enabled(self):
        cid = uuid.uuid4()
        clause, params = _build_where_clause(cid, chat_enabled_only=True)
        assert "channel_id" in clause
        assert "chat_enabled" in clause
        assert "AND" in clause

    def test_neither_filter(self):
        clause, params = _build_where_clause(None, chat_enabled_only=False)
        assert clause == ""
        assert params == {}


class TestSemanticSearchChatFilter:
    @pytest.mark.asyncio
    @patch("app.services.search._vector_search", new_callable=AsyncMock)
    async def test_chat_enabled_only_passed_to_vector(self, mock_vector):
        mock_vector.return_value = []
        db = AsyncMock()
        await semantic_search(
            db, FAKE_EMBEDDING, limit=10,
            search_mode="vector", chat_enabled_only=True,
        )
        mock_vector.assert_called_once()
        call_kwargs = mock_vector.call_args
        assert call_kwargs[1].get("chat_enabled_only") is True or call_kwargs[0][-1] is True

    @pytest.mark.asyncio
    @patch("app.services.search._keyword_search", new_callable=AsyncMock)
    async def test_chat_enabled_only_passed_to_keyword(self, mock_keyword):
        mock_keyword.return_value = []
        db = AsyncMock()
        await semantic_search(
            db, FAKE_EMBEDDING, limit=10, query="test",
            search_mode="keyword", chat_enabled_only=True,
        )
        mock_keyword.assert_called_once()
        _, kwargs = mock_keyword.call_args
        # chat_enabled_only should be passed as positional or keyword arg
        call_args_all = mock_keyword.call_args
        assert True in call_args_all[0] or kwargs.get("chat_enabled_only") is True

    @pytest.mark.asyncio
    @patch("app.services.search._hybrid_search", new_callable=AsyncMock)
    async def test_chat_enabled_only_passed_to_hybrid(self, mock_hybrid):
        mock_hybrid.return_value = []
        db = AsyncMock()
        await semantic_search(
            db, FAKE_EMBEDDING, limit=10, query="test",
            search_mode="hybrid", chat_enabled_only=True,
        )
        mock_hybrid.assert_called_once()
        _, kwargs = mock_hybrid.call_args
        assert kwargs.get("chat_enabled_only") is True

    @pytest.mark.asyncio
    @patch("app.services.search._vector_search", new_callable=AsyncMock)
    async def test_default_chat_enabled_only_is_false(self, mock_vector):
        mock_vector.return_value = []
        db = AsyncMock()
        await semantic_search(
            db, FAKE_EMBEDDING, limit=10, search_mode="vector",
        )
        call_args = mock_vector.call_args
        # Default should be False
        assert call_args[0][-1] is False or call_args[1].get("chat_enabled_only", False) is False

    @pytest.mark.asyncio
    @patch("app.services.search._vector_search", new_callable=AsyncMock)
    async def test_search_returns_empty_when_all_disabled(self, mock_vector):
        """Search with chat_enabled_only=True returns empty list, not error."""
        mock_vector.return_value = []
        db = AsyncMock()
        results = await semantic_search(
            db, FAKE_EMBEDDING, limit=10,
            search_mode="vector", chat_enabled_only=True,
        )
        assert results == []

    @pytest.mark.asyncio
    @patch("app.services.search._keyword_search", new_callable=AsyncMock)
    async def test_keyword_search_returns_empty_when_all_disabled(self, mock_keyword):
        """Keyword search with chat_enabled_only=True returns empty list, not error."""
        mock_keyword.return_value = []
        db = AsyncMock()
        results = await semantic_search(
            db, FAKE_EMBEDDING, limit=10, query="test",
            search_mode="keyword", chat_enabled_only=True,
        )
        assert results == []

    @pytest.mark.asyncio
    @patch("app.services.search._hybrid_search", new_callable=AsyncMock)
    async def test_hybrid_search_returns_empty_when_all_disabled(self, mock_hybrid):
        """Hybrid search with chat_enabled_only=True returns empty list, not error."""
        mock_hybrid.return_value = []
        db = AsyncMock()
        results = await semantic_search(
            db, FAKE_EMBEDDING, limit=10, query="test",
            search_mode="hybrid", chat_enabled_only=True,
        )
        assert results == []
