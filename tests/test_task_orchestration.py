from dataclasses import dataclass
from types import SimpleNamespace

from app.tasks import batch_progress, pipeline


def test_run_pipeline_builds_expected_chain(monkeypatch):
    calls = []

    def fake_signature(name, args=None, app=None):
        calls.append((name, args, app))
        return name

    class FakeChain:
        def apply_async(self):
            return SimpleNamespace(id="chain-123")

    def fake_chain(*parts):
        assert parts == (
            "tasks.download_audio",
            "tasks.transcribe_audio",
            "tasks.summarize_transcription",
            "tasks.generate_embeddings",
        )
        return FakeChain()

    monkeypatch.setattr(pipeline, "signature", fake_signature)
    monkeypatch.setattr(pipeline, "chain", fake_chain)

    result_id = pipeline.run_pipeline("video-1")

    assert result_id == "chain-123"
    assert [c[0] for c in calls] == [
        "tasks.download_audio",
        "tasks.transcribe_audio",
        "tasks.summarize_transcription",
        "tasks.generate_embeddings",
    ]
    assert calls[0][1] == ["video-1"]
    assert calls[1][1] is None
    assert calls[2][1] is None
    assert calls[3][1] is None


@dataclass
class FakeBatch:
    id: str
    channel_id: str
    batch_number: int
    status: str = "running"
    completed_videos: int = 0
    failed_videos: int = 0
    completed_at: object = None


@dataclass
class FakeJob:
    status: str
    video_id: str | None = None
    celery_task_id: str | None = None
    progress_pct: float = 0.0
    progress_message: str | None = None
    error_message: str | None = None
    started_at: object = None
    completed_at: object = None


class _FakeJobQuery:
    def __init__(self, db):
        self.db = db

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        self.db.job_all_calls += 1
        if self.db.job_all_calls == 1:
            return self.db.current_jobs
        return self.db.next_jobs


class _FakeBatchQuery:
    def __init__(self, db):
        self.db = db

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def with_for_update(self, *args, **kwargs):
        return self

    def first(self):
        return self.db.next_batch


class FakeDB:
    def __init__(self, batch, current_jobs, next_batch=None, next_jobs=None):
        self.batch = batch
        self.current_jobs = current_jobs
        self.next_batch = next_batch
        self.next_jobs = next_jobs or []
        self.job_all_calls = 0

    def get(self, model, batch_id):
        if batch_id == self.batch.id:
            return self.batch
        return None

    def query(self, model):
        if model is batch_progress.Job:
            return _FakeJobQuery(self)
        if model is batch_progress.Batch:
            return _FakeBatchQuery(self)
        raise AssertionError(f"Unexpected model query: {model}")


def test_update_batch_progress_noop_when_batch_missing(monkeypatch):
    called = []
    monkeypatch.setattr(batch_progress, "run_pipeline", lambda video_id: called.append(video_id))

    class MissingBatchDB(FakeDB):
        def get(self, model, batch_id):
            return None

    db = MissingBatchDB(
        batch=FakeBatch(id="b1", channel_id="c1", batch_number=1),
        current_jobs=[],
    )

    batch_progress.update_batch_progress_and_maybe_advance(db, "does-not-exist")

    assert called == []


def test_update_batch_progress_does_not_advance_for_non_terminal_batch(monkeypatch):
    called = []
    monkeypatch.setattr(batch_progress, "run_pipeline", lambda video_id: called.append(video_id))

    batch = FakeBatch(id="b1", channel_id="c1", batch_number=1)
    current_jobs = [FakeJob(status="completed"), FakeJob(status="running")]
    next_batch = FakeBatch(id="b2", channel_id="c1", batch_number=2, status="pending")
    next_jobs = [FakeJob(status="pending", video_id="vid-2")]
    db = FakeDB(batch=batch, current_jobs=current_jobs, next_batch=next_batch, next_jobs=next_jobs)

    batch_progress.update_batch_progress_and_maybe_advance(db, "b1")

    assert batch.completed_videos == 1
    assert batch.failed_videos == 0
    assert batch.status == "running"
    assert next_batch.status == "pending"
    assert called == []


def test_update_batch_progress_advances_and_enqueues_next_batch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        batch_progress,
        "run_pipeline",
        lambda video_id: calls.append(video_id) or f"task-{video_id}",
    )

    batch = FakeBatch(id="b1", channel_id="c1", batch_number=1)
    current_jobs = [FakeJob(status="completed"), FakeJob(status="failed")]
    next_batch = FakeBatch(id="b2", channel_id="c1", batch_number=2, status="pending")
    next_jobs = [
        FakeJob(status="pending", video_id="vid-2"),
        FakeJob(status="pending", video_id="vid-3", celery_task_id="already-set"),
        FakeJob(status="pending", video_id=None),
    ]
    db = FakeDB(batch=batch, current_jobs=current_jobs, next_batch=next_batch, next_jobs=next_jobs)

    batch_progress.update_batch_progress_and_maybe_advance(db, "b1")

    assert batch.status == "failed"
    assert batch.completed_videos == 1
    assert batch.failed_videos == 1
    assert batch.completed_at is not None
    assert next_batch.status == "running"
    assert calls == ["vid-2"]
    assert next_jobs[0].status == "queued"
    assert next_jobs[0].celery_task_id == "task-vid-2"
    assert next_jobs[1].celery_task_id == "already-set"
