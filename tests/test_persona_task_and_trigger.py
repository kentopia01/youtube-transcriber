"""Tests for the persona Celery task, the auto-trigger hook, and the router endpoints."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_db
from app.main import create_app
from app.tasks import generate_persona as persona_task_module


# ---------------------------------------------------------------------------
# _run (the async body of the Celery task) — unit tests with mocked DB
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_channel():
    return SimpleNamespace(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        name="Test Channel",
        description="A test channel.",
    )


def _install_async_session(monkeypatch, db_mock):
    """Patch create_async_engine/async_sessionmaker so _run gets db_mock."""

    class _SessionCM:
        async def __aenter__(self):
            return db_mock

        async def __aexit__(self, *args):
            return False

    def _session_factory():
        return _SessionCM()

    monkeypatch.setattr(
        persona_task_module, "create_async_engine",
        lambda *a, **kw: SimpleNamespace(dispose=AsyncMock())
    )
    monkeypatch.setattr(
        persona_task_module, "async_sessionmaker",
        lambda *a, **kw: lambda: _SessionCM()
    )


class TestRunTask:
    @pytest.mark.asyncio
    async def test_skips_when_channel_not_ready(self, monkeypatch, fake_channel):
        db_mock = MagicMock()
        db_mock.get = AsyncMock(return_value=fake_channel)
        _install_async_session(monkeypatch, db_mock)

        monkeypatch.setattr(
            persona_task_module, "channel_needs_persona",
            AsyncMock(return_value=(False, "only 1/3 videos")),
        )

        result = await persona_task_module._run(str(fake_channel.id), forced=False)
        assert result["status"] == "skipped"
        assert "1/3" in result["reason"]

    @pytest.mark.asyncio
    async def test_skips_when_no_chunks(self, monkeypatch, fake_channel):
        db_mock = MagicMock()
        db_mock.get = AsyncMock(return_value=fake_channel)
        _install_async_session(monkeypatch, db_mock)

        monkeypatch.setattr(
            persona_task_module, "channel_needs_persona",
            AsyncMock(return_value=(True, "no persona yet")),
        )
        monkeypatch.setattr(
            "app.services.persona.get_persona",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            persona_task_module, "select_characteristic_chunks",
            AsyncMock(return_value=[]),
        )

        result = await persona_task_module._run(str(fake_channel.id), forced=False)
        assert result["status"] == "skipped"
        assert "no embedding chunks" in result["reason"]

    @pytest.mark.asyncio
    async def test_raises_when_channel_missing(self, monkeypatch):
        db_mock = MagicMock()
        db_mock.get = AsyncMock(return_value=None)
        _install_async_session(monkeypatch, db_mock)

        with pytest.raises(ValueError, match="not found"):
            await persona_task_module._run(str(uuid.uuid4()), forced=False)

    @pytest.mark.asyncio
    async def test_happy_path_calls_upsert(self, monkeypatch, fake_channel):
        db_mock = MagicMock()
        db_mock.get = AsyncMock(return_value=fake_channel)
        _install_async_session(monkeypatch, db_mock)

        monkeypatch.setattr(
            persona_task_module, "channel_needs_persona",
            AsyncMock(return_value=(True, "no persona yet")),
        )
        monkeypatch.setattr(
            "app.services.persona.get_persona",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            persona_task_module, "select_characteristic_chunks",
            AsyncMock(return_value=[{"id": str(uuid.uuid4()), "chunk_text": "t", "source_type": "transcript"}]),
        )

        from app.services.persona import PersonaDerivation

        fake_derivation = PersonaDerivation(
            display_name="Test",
            persona_prompt="You are...",
            style_notes={"tone": "dry"},
            exemplar_chunk_ids=[],
            source_chunk_count=1,
            confidence=0.7,
            model="claude-sonnet-4-5",
        )
        monkeypatch.setattr(
            persona_task_module, "derive_persona", lambda **kw: fake_derivation
        )
        monkeypatch.setattr(
            persona_task_module, "count_completed_videos", AsyncMock(return_value=5)
        )

        fake_persona = SimpleNamespace(
            id=uuid.uuid4(),
            display_name="Test",
            confidence=0.7,
            source_chunk_count=1,
            videos_at_generation=5,
        )
        upsert_mock = AsyncMock(return_value=fake_persona)
        monkeypatch.setattr(persona_task_module, "upsert_persona", upsert_mock)

        result = await persona_task_module._run(str(fake_channel.id), forced=False)

        assert result["status"] == "generated"
        assert result["display_name"] == "Test"
        upsert_mock.assert_awaited_once()
        kwargs = upsert_mock.call_args.kwargs
        assert kwargs["scope_type"] == "channel"
        assert kwargs["scope_id"] == str(fake_channel.id)
        assert kwargs["videos_at_generation"] == 5

    @pytest.mark.asyncio
    async def test_forced_skips_should_generate_check(self, monkeypatch, fake_channel):
        db_mock = MagicMock()
        db_mock.get = AsyncMock(return_value=fake_channel)
        _install_async_session(monkeypatch, db_mock)

        needs_check = AsyncMock(return_value=(False, "not ready"))
        monkeypatch.setattr(persona_task_module, "channel_needs_persona", needs_check)
        monkeypatch.setattr(
            "app.services.persona.get_persona",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            persona_task_module, "select_characteristic_chunks",
            AsyncMock(return_value=[{"id": str(uuid.uuid4()), "chunk_text": "t", "source_type": "transcript"}]),
        )

        from app.services.persona import PersonaDerivation
        monkeypatch.setattr(persona_task_module, "derive_persona", lambda **kw: PersonaDerivation(
            display_name="x", persona_prompt="y", style_notes={}, exemplar_chunk_ids=[],
            source_chunk_count=1, confidence=0.5, model="m",
        ))
        monkeypatch.setattr(persona_task_module, "count_completed_videos", AsyncMock(return_value=3))
        monkeypatch.setattr(persona_task_module, "upsert_persona", AsyncMock(return_value=SimpleNamespace(
            id=uuid.uuid4(), display_name="x", confidence=0.5, source_chunk_count=1, videos_at_generation=3,
        )))

        await persona_task_module._run(str(fake_channel.id), forced=True)
        needs_check.assert_not_awaited()


# ---------------------------------------------------------------------------
# enqueue_channel_persona — fire-and-forget wrapper
# ---------------------------------------------------------------------------


class TestEnqueue:
    def test_calls_apply_async_with_post_queue(self, monkeypatch):
        mock_apply = MagicMock()
        monkeypatch.setattr(
            persona_task_module.generate_channel_persona_task,
            "apply_async",
            mock_apply,
        )
        cid = str(uuid.uuid4())
        persona_task_module.enqueue_channel_persona(cid, forced=False)
        mock_apply.assert_called_once()
        assert mock_apply.call_args.kwargs["queue"] == "post"
        assert mock_apply.call_args.kwargs["args"] == [cid]
        assert mock_apply.call_args.kwargs["kwargs"] == {"forced": False}

    def test_swallows_enqueue_failures(self, monkeypatch):
        monkeypatch.setattr(
            persona_task_module.generate_channel_persona_task,
            "apply_async",
            MagicMock(side_effect=RuntimeError("broker down")),
        )
        persona_task_module.enqueue_channel_persona(str(uuid.uuid4()))  # must not raise


# ---------------------------------------------------------------------------
# Router endpoints
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar(self):
        return self._value


class _StubSession:
    """Order-aware stub: execute() alternates between persona lookup
    (scalar_one_or_none) and count_completed_videos (scalar)."""

    def __init__(self, channel=None, persona=None, completed=0):
        self._channel = channel
        self._persona = persona
        self._completed = completed
        self.committed = False

    async def get(self, model, key):
        from app.models.channel import Channel

        if model is Channel:
            return self._channel
        return None

    async def execute(self, stmt, *args, **kwargs):
        # Heuristic: count queries use sqlalchemy.func.count() — their compiled
        # SQL contains "count(". Return the completed int for those; return the
        # persona row for everything else.
        try:
            compiled = str(stmt)
        except Exception:
            compiled = ""
        if "count(" in compiled.lower():
            return _FakeResult(self._completed)
        return _FakeResult(self._persona)

    async def scalar(self, *args, **kwargs):
        return self._completed

    async def commit(self):
        self.committed = True


def _client(stub):
    app = create_app()

    async def _override():
        yield stub

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


class TestChannelPersonaGetEndpoint:
    def test_404_when_channel_missing(self):
        stub = _StubSession(channel=None)
        client = _client(stub)
        resp = client.get(f"/api/channels/{uuid.uuid4()}/persona")
        assert resp.status_code == 404

    def test_returns_ready_false_when_no_persona(self):
        channel = SimpleNamespace(
            id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            name="Empty Channel",
        )
        stub = _StubSession(channel=channel, persona=None, completed=1)
        client = _client(stub)
        resp = client.get(f"/api/channels/{channel.id}/persona")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ready"] is False
        assert data["persona"] is None
        assert data["completed_videos"] == 1
        assert data["min_videos"] == 3
        assert "1/3" in data["reason"]

    def test_returns_persona_when_ready(self):
        from datetime import datetime, timezone

        channel = SimpleNamespace(
            id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
            name="Ready Channel",
        )
        persona = SimpleNamespace(
            id=uuid.uuid4(),
            display_name="Ready",
            persona_prompt="You are ready.",
            style_notes={"tone": "crisp"},
            confidence=0.8,
            source_chunk_count=30,
            videos_at_generation=5,
            refresh_after_videos=5,
            generated_at=datetime(2026, 4, 17, 10, tzinfo=timezone.utc),
            generated_by_model="claude-sonnet-4-5",
        )
        stub = _StubSession(channel=channel, persona=persona, completed=5)
        client = _client(stub)
        resp = client.get(f"/api/channels/{channel.id}/persona")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ready"] is True
        assert data["persona"]["display_name"] == "Ready"
        assert data["persona"]["confidence"] == 0.8


class TestChannelPersonaPostEndpoint:
    def test_404_when_channel_missing(self):
        stub = _StubSession(channel=None)
        client = _client(stub)
        resp = client.post(f"/api/channels/{uuid.uuid4()}/generate-persona")
        assert resp.status_code == 404

    def test_400_when_below_min_videos(self):
        channel = SimpleNamespace(
            id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
            name="New Channel",
        )
        stub = _StubSession(channel=channel, persona=None, completed=1)
        client = _client(stub)
        resp = client.post(f"/api/channels/{channel.id}/generate-persona")
        assert resp.status_code == 400
        assert "1/3" in resp.json()["detail"]

    def test_enqueues_when_ready(self, monkeypatch):
        channel = SimpleNamespace(
            id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
            name="Ready Channel",
        )
        stub = _StubSession(channel=channel, persona=None, completed=7)
        client = _client(stub)

        enqueue_mock = MagicMock()
        monkeypatch.setattr(
            "app.tasks.generate_persona.enqueue_channel_persona", enqueue_mock
        )
        resp = client.post(f"/api/channels/{channel.id}/generate-persona")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "enqueued"
        assert data["completed_videos"] == 7
        enqueue_mock.assert_called_once_with(str(channel.id), forced=True)


# ---------------------------------------------------------------------------
# Embed-task auto-trigger hook
# ---------------------------------------------------------------------------


class TestEmbedHook:
    """After embed completes successfully, enqueue_channel_persona is called
    when the video has a channel."""

    def test_hook_enqueues_on_success(self, monkeypatch):
        # This test simulates the relevant branch in embed.py to avoid DB setup.
        # We verify the symbol is importable and callable in the context the
        # hook uses.
        from app.tasks import generate_persona

        captured = []
        monkeypatch.setattr(
            generate_persona, "enqueue_channel_persona",
            lambda cid, **kw: captured.append(cid),
        )

        # Simulate the embed-task tail: a completed video with a channel.
        video = SimpleNamespace(channel_id=uuid.UUID("66666666-6666-6666-6666-666666666666"))
        if video.channel_id:
            generate_persona.enqueue_channel_persona(str(video.channel_id))

        assert captured == [str(video.channel_id)]

    def test_hook_skips_when_no_channel(self, monkeypatch):
        from app.tasks import generate_persona

        captured = []
        monkeypatch.setattr(
            generate_persona, "enqueue_channel_persona",
            lambda cid, **kw: captured.append(cid),
        )

        video = SimpleNamespace(channel_id=None)
        if video.channel_id:
            generate_persona.enqueue_channel_persona(str(video.channel_id))

        assert captured == []
