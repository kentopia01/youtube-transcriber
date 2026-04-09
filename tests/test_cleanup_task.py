from types import SimpleNamespace
import uuid

import pytest

from app.tasks import cleanup


class _FakeQuery:
    def __init__(self, transcription):
        self.transcription = transcription

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.transcription


class _FakeDB:
    def __init__(self, transcription):
        self.transcription = transcription
        self.commits = 0

    def query(self, model):
        assert model is cleanup.Transcription
        return _FakeQuery(self.transcription)

    def commit(self):
        self.commits += 1


class _FakeSessionContext:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, exc, tb):
        return False


def test_cleanup_task_uses_service_contract_and_updates_models(monkeypatch):
    monkeypatch.setattr(cleanup.settings, "transcript_cleanup_enabled", True)
    monkeypatch.setattr(cleanup.settings, "anthropic_api_key", "api-key")
    monkeypatch.setattr(cleanup.settings, "anthropic_cleanup_model", "cleanup-model")

    payload = {"video_id": "vid-1", "job_id": "job-1"}
    video = SimpleNamespace(id=uuid.uuid4(), status=None)
    job = SimpleNamespace(batch_id=None)
    segments = [
        SimpleNamespace(start_time=0.0, end_time=1.0, text="um hello", confidence=0.9, speaker="SPEAKER_00"),
        SimpleNamespace(start_time=1.0, end_time=2.0, text="uh world", confidence=0.8, speaker="SPEAKER_01"),
    ]
    transcription = SimpleNamespace(segments=segments, full_text="um hello uh world")

    db = _FakeDB(transcription)
    monkeypatch.setattr(cleanup, "Session", lambda _engine: _FakeSessionContext(db))
    monkeypatch.setattr(
        cleanup,
        "get_pipeline_job_context",
        lambda _db, _payload, expected_stage: (payload, video, job),
    )
    monkeypatch.setattr(cleanup, "update_pipeline_job", lambda *_args, **_kwargs: None)

    observed = {}

    def fake_clean_transcript(segment_payload, api_key, model):
        observed["segment_payload"] = segment_payload
        observed["api_key"] = api_key
        observed["model"] = model
        return [
            {"text": "hello", "speaker": "SPEAKER_00"},
            {"text": "world", "speaker": "SPEAKER_01"},
        ]

    monkeypatch.setattr(cleanup, "clean_transcript", fake_clean_transcript)

    result = cleanup.cleanup_transcript_task.run(payload)

    assert result == payload
    assert observed["api_key"] == "api-key"
    assert observed["model"] == "cleanup-model"
    assert observed["segment_payload"] == [
        {
            "start": 0.0,
            "end": 1.0,
            "text": "um hello",
            "confidence": 0.9,
            "speaker": "SPEAKER_00",
        },
        {
            "start": 1.0,
            "end": 2.0,
            "text": "uh world",
            "confidence": 0.8,
            "speaker": "SPEAKER_01",
        },
    ]
    assert segments[0].text == "hello"
    assert segments[1].text == "world"
    assert transcription.full_text == "hello world"
    assert video.status == "cleaned"


def test_cleanup_task_records_failure_and_raises(monkeypatch):
    monkeypatch.setattr(cleanup.settings, "transcript_cleanup_enabled", True)
    monkeypatch.setattr(cleanup.settings, "anthropic_api_key", "api-key")
    monkeypatch.setattr(cleanup.settings, "anthropic_cleanup_model", "cleanup-model")

    payload = {"video_id": "vid-1", "job_id": "job-1"}
    video = SimpleNamespace(id=uuid.uuid4(), status=None)
    job = SimpleNamespace(batch_id="batch-1")
    transcription = SimpleNamespace(
        segments=[SimpleNamespace(start_time=0.0, end_time=1.0, text="um hello", confidence=0.9, speaker=None)],
        full_text="um hello",
    )

    db = _FakeDB(transcription)
    monkeypatch.setattr(cleanup, "Session", lambda _engine: _FakeSessionContext(db))
    monkeypatch.setattr(
        cleanup,
        "get_pipeline_job_context",
        lambda _db, _payload, expected_stage: (payload, video, job),
    )
    monkeypatch.setattr(cleanup, "update_pipeline_job", lambda *_args, **_kwargs: None)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("cleanup boom")

    monkeypatch.setattr(cleanup, "clean_transcript", _boom)

    failure_calls = []
    monkeypatch.setattr(
        cleanup,
        "record_pipeline_failure",
        lambda *args, **kwargs: failure_calls.append(kwargs),
    )
    batch_calls = []
    monkeypatch.setattr(
        cleanup,
        "update_batch_progress_and_maybe_advance",
        lambda _db, batch_id: batch_calls.append(batch_id),
    )

    with pytest.raises(RuntimeError, match="cleanup boom"):
        cleanup.cleanup_transcript_task.run(payload)

    assert len(failure_calls) == 1
    assert failure_calls[0]["stage"] == cleanup.PIPELINE_STAGE_CLEANUP
    assert batch_calls == ["batch-1"]
