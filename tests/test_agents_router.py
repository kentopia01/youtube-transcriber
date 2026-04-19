"""Tests for the channel-persona agent router."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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
        return self

    def all(self):
        if isinstance(self._value, list):
            return self._value
        return []


class _Stub:
    """Tiny async session stub for the agents router.

    Configure:
      - channel: SimpleNamespace returned for Channel lookups (or None → 404)
      - persona: returned for the first execute() call (persona lookup)
      - session: returned for the second execute() call (session lookup)
      - messages: returned for the third execute() call (recent history)
    """

    def __init__(self, channel=None, persona=None, session=None, messages=None):
        self._channel = channel
        self._persona = persona
        self._session = session
        self._messages = messages or []
        self.added = []
        self.committed = False
        self._call_idx = 0

    async def get(self, model, key):
        from app.models.channel import Channel

        if model is Channel:
            return self._channel
        return None

    async def execute(self, *args, **kwargs):
        idx = self._call_idx
        self._call_idx += 1
        # Router call order inside message handler:
        #   1. persona lookup (scalar_one_or_none → persona or None)
        #   2. session lookup (scalar_one_or_none → session or None)
        #   3. history query (scalars().all() → messages)
        if idx == 0:
            return _FakeResult(self._persona)
        if idx == 1:
            return _FakeResult(self._session)
        return _FakeResult(self._messages)

    def add(self, obj):
        obj.id = getattr(obj, "id", None) or uuid.uuid4()
        obj.session_id = getattr(obj, "session_id", None)
        from datetime import UTC, datetime as _dt
        obj.created_at = _dt.now(UTC)
        obj.updated_at = _dt.now(UTC)
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        return obj


def _client(stub):
    app = create_app()

    async def _override():
        yield stub

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


FAKE_CHANNEL_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
FAKE_PERSONA_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
FAKE_SESSION_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


def _fake_channel():
    return SimpleNamespace(id=FAKE_CHANNEL_ID, name="Fake Channel")


def _fake_persona():
    from datetime import UTC, datetime
    return SimpleNamespace(
        id=FAKE_PERSONA_ID,
        scope_type="channel",
        scope_id=str(FAKE_CHANNEL_ID),
        display_name="Fake Voice",
        persona_prompt="You are Fake Voice.",
        style_notes={"tone": "dry"},
        exemplar_chunk_ids=[],
        source_chunk_count=5,
        confidence=0.7,
        generated_by_model="claude-sonnet-4-5",
        generated_at=datetime(2026, 4, 17, tzinfo=UTC),
        videos_at_generation=3,
        refresh_after_videos=5,
    )


def _fake_session():
    from datetime import UTC, datetime
    return SimpleNamespace(
        id=FAKE_SESSION_ID,
        persona_id=FAKE_PERSONA_ID,
        title=None,
        platform="web",
        telegram_chat_id=None,
        created_at=datetime(2026, 4, 17, tzinfo=UTC),
        updated_at=datetime(2026, 4, 17, tzinfo=UTC),
    )


class TestCreateSession:
    def test_404_when_channel_missing(self):
        stub = _Stub(channel=None)
        client = _client(stub)
        resp = client.post(f"/api/agents/channel/{FAKE_CHANNEL_ID}/sessions")
        assert resp.status_code == 404

    def test_409_when_persona_missing(self):
        stub = _Stub(channel=_fake_channel(), persona=None)
        client = _client(stub)
        resp = client.post(f"/api/agents/channel/{FAKE_CHANNEL_ID}/sessions")
        assert resp.status_code == 409
        assert "persona" in resp.json()["detail"].lower()

    def test_creates_session_bound_to_persona(self):
        stub = _Stub(channel=_fake_channel(), persona=_fake_persona())
        client = _client(stub)
        resp = client.post(f"/api/agents/channel/{FAKE_CHANNEL_ID}/sessions")
        assert resp.status_code == 200
        # session was added to DB
        sessions = [obj for obj in stub.added if hasattr(obj, "persona_id")]
        assert len(sessions) == 1
        assert sessions[0].persona_id == FAKE_PERSONA_ID
        assert "Fake Voice" in sessions[0].title


class TestSendMessage:
    def test_404_when_channel_missing(self):
        stub = _Stub(channel=None)
        client = _client(stub)
        resp = client.post(
            f"/api/agents/channel/{FAKE_CHANNEL_ID}/sessions/{FAKE_SESSION_ID}/messages",
            json={"content": "hi"},
        )
        assert resp.status_code == 404

    def test_409_when_persona_missing(self):
        stub = _Stub(channel=_fake_channel(), persona=None)
        client = _client(stub)
        resp = client.post(
            f"/api/agents/channel/{FAKE_CHANNEL_ID}/sessions/{FAKE_SESSION_ID}/messages",
            json={"content": "hi"},
        )
        assert resp.status_code == 409

    def test_404_when_session_missing_for_channel(self):
        stub = _Stub(channel=_fake_channel(), persona=_fake_persona(), session=None)
        client = _client(stub)
        resp = client.post(
            f"/api/agents/channel/{FAKE_CHANNEL_ID}/sessions/{FAKE_SESSION_ID}/messages",
            json={"content": "hi"},
        )
        assert resp.status_code == 404

    def test_happy_path_calls_chat_with_persona_and_channel(self, monkeypatch):
        stub = _Stub(
            channel=_fake_channel(),
            persona=_fake_persona(),
            session=_fake_session(),
            messages=[],
        )
        client = _client(stub)

        chat_mock = AsyncMock(
            return_value={
                "content": "hello from fake voice",
                "sources": [],
                "model": "claude-haiku-4-5",
                "prompt_tokens": 100,
                "completion_tokens": 20,
            }
        )
        monkeypatch.setattr("app.routers.agents.chat_with_context", chat_mock)
        monkeypatch.setattr(
            "app.routers.agents.get_exemplar_chunks",
            AsyncMock(return_value=[]),
        )

        resp = client.post(
            f"/api/agents/channel/{FAKE_CHANNEL_ID}/sessions/{FAKE_SESSION_ID}/messages",
            json={"content": "hi there"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["content"] == "hello from fake voice"

        chat_mock.assert_awaited_once()
        kwargs = chat_mock.call_args.kwargs
        assert kwargs["channel_id"] == FAKE_CHANNEL_ID
        assert "Fake Voice" in kwargs["system_prompt"]
        # citation suffix was appended
        assert "cite" in kwargs["system_prompt"].lower()


class TestSystemPromptComposition:
    def test_persona_prompt_is_suffixed_with_citation_rules(self):
        from app.services.persona import compose_persona_system_prompt

        persona = _fake_persona()
        out = compose_persona_system_prompt(persona)
        assert out.startswith("You are Fake Voice.")
        assert "cite" in out.lower()
        # Perplexity-style prompt lives here; verify format markers present.
        assert "[1]" in out
        assert "Related:" in out
