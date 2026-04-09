from types import SimpleNamespace

from app.models.batch import Batch
from app.models.job import Job
from app.services import channel_dispatcher


class FakeQuery:
    def __init__(self, items):
        self.items = list(items)
        self._limit = None

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, value):
        self._limit = value
        return self

    def all(self):
        if self._limit is None:
            return list(self.items)
        return list(self.items)[: self._limit]

    def first(self):
        items = self.all()
        return items[0] if items else None

    def count(self):
        return len(self.items)

    def first(self):
        items = self.all()
        return items[0] if items else None


class FakeDB:
    def __init__(self, batches, pending_jobs):
        self.batches = batches
        self.pending_jobs = pending_jobs
        self.flushed = False

    def query(self, model):
        if model is Batch:
            return FakeQuery(self.batches)
        if model is Job:
            return FakeQuery(self.pending_jobs)
        raise AssertionError(f"Unexpected model: {model}")

    def flush(self):
        self.flushed = True


def test_promote_pending_channel_jobs_noops_when_manual_job_active(monkeypatch):
    db = FakeDB(
        batches=[SimpleNamespace(id="batch-1", status="running")],
        pending_jobs=[SimpleNamespace(id="job-1", video_id="video-1", celery_task_id=None, status="pending")],
    )

    monkeypatch.setattr(channel_dispatcher, "_active_manual_jobs_exist", lambda _db: True)
    monkeypatch.setattr(
        channel_dispatcher,
        "_active_channel_jobs_count",
        lambda _db: sum(1 for job in _db.pending_jobs if getattr(job, "status", None) in channel_dispatcher.CHANNEL_JOB_ACTIVE),
    )
    monkeypatch.setattr(channel_dispatcher, "run_pipeline", lambda *args, **kwargs: "should-not-run")

    promoted = channel_dispatcher.promote_pending_channel_jobs(db, limit=1)

    assert promoted == []
    assert db.pending_jobs[0].celery_task_id is None
    assert db.pending_jobs[0].status == "pending"


def test_promote_pending_channel_jobs_dispatches_one_pending_job(monkeypatch):
    batch = SimpleNamespace(id="batch-1", status="running")
    pending_job = SimpleNamespace(
        id="job-1",
        video_id="video-1",
        celery_task_id=None,
        status="pending",
        lifecycle_status="pending",
        current_stage="queued",
        progress_pct=0.0,
        progress_message="Waiting for channel dispatcher",
        error_message=None,
        started_at=None,
        completed_at=None,
    )
    db = FakeDB(batches=[batch], pending_jobs=[pending_job])

    monkeypatch.setattr(channel_dispatcher, "_active_manual_jobs_exist", lambda _db: False)
    monkeypatch.setattr(
        channel_dispatcher,
        "_active_channel_jobs_count",
        lambda _db: sum(1 for job in _db.pending_jobs if getattr(job, "status", None) in channel_dispatcher.CHANNEL_JOB_ACTIVE),
    )
    monkeypatch.setattr(channel_dispatcher, "run_pipeline", lambda video_id, job_id=None: f"task-{video_id}-{job_id}")

    promoted = channel_dispatcher.promote_pending_channel_jobs(db, limit=1)

    assert promoted == ["job-1"]
    assert pending_job.status == "queued"
    assert pending_job.progress_message == "Queued by channel dispatcher"
    assert pending_job.celery_task_id == "task-video-1-job-1"
