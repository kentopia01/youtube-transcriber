from types import SimpleNamespace

import pytest

from app.models.batch import Batch
from app.models.job import Job
from app.services import channel_dispatcher
from app.services.pipeline_enqueue import PipelineEnqueueError


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
        self.events = []

    def get(self, model, object_id):
        if model is Batch:
            return next((batch for batch in self.batches if batch.id == object_id), None)
        raise AssertionError(f"Unexpected model: {model}")

    def query(self, model):
        if model is Batch:
            return FakeQuery(self.batches)
        if model is Job:
            return FakeQuery(self.pending_jobs)
        raise AssertionError(f"Unexpected model: {model}")

    def flush(self):
        self.flushed = True

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")


def _count_active_channel_jobs(db):
    return sum(
        1
        for job in db.pending_jobs
        if getattr(job, "status", None) in channel_dispatcher.CHANNEL_JOB_ACTIVE
    )


def test_promote_pending_channel_jobs_noops_when_manual_job_active(monkeypatch):
    db = FakeDB(
        batches=[SimpleNamespace(id="batch-1", status="running")],
        pending_jobs=[SimpleNamespace(id="job-1", video_id="video-1", celery_task_id=None, status="pending")],
    )

    monkeypatch.setattr(channel_dispatcher, "_active_manual_jobs_exist", lambda _db: True)
    monkeypatch.setattr(channel_dispatcher, "_active_channel_jobs_count", _count_active_channel_jobs)
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
    monkeypatch.setattr(channel_dispatcher, "_active_channel_jobs_count", _count_active_channel_jobs)

    def _publish(video_id, job_id=None):
        assert db.events == ["commit"]
        db.events.append("publish")
        return f"task-{video_id}-{job_id}"

    monkeypatch.setattr(channel_dispatcher, "run_pipeline", _publish)

    promoted = channel_dispatcher.promote_pending_channel_jobs(db, limit=1)

    assert promoted == ["job-1"]
    assert pending_job.status == "queued"
    assert pending_job.progress_message == "Queued by channel dispatcher"
    assert pending_job.celery_task_id == "task-video-1-job-1"
    assert db.events == ["commit", "publish", "commit"]


def test_promote_pending_channel_jobs_marks_job_failed_when_publish_fails(monkeypatch):
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
    monkeypatch.setattr(channel_dispatcher, "_active_channel_jobs_count", lambda _db: 0)

    def _publish(video_id, job_id=None):
        assert db.events == ["commit"]
        db.events.append("publish")
        raise RuntimeError("broker offline")

    monkeypatch.setattr(channel_dispatcher, "run_pipeline", _publish)

    with pytest.raises(PipelineEnqueueError):
        channel_dispatcher.promote_pending_channel_jobs(db, limit=1)

    assert pending_job.status == "failed"
    assert pending_job.current_stage == "queued"
    assert pending_job.celery_task_id is None
    assert "broker offline" in pending_job.error_message
    assert db.events == ["commit", "publish", "commit"]


def test_refresh_batch_progress_all_failed_uses_completed_with_errors():
    batch = SimpleNamespace(
        id="batch-1",
        status="running",
        completed_videos=0,
        failed_videos=0,
        completed_at=None,
    )
    jobs = [
        SimpleNamespace(id="job-1", status="failed"),
        SimpleNamespace(id="job-2", status="cancelled"),
    ]
    db = FakeDB(batches=[batch], pending_jobs=jobs)

    refreshed = channel_dispatcher.refresh_batch_progress(db, "batch-1")

    assert refreshed is batch
    assert batch.status == "completed_with_errors"
    assert batch.completed_videos == 0
    assert batch.failed_videos == 2
    assert batch.completed_at is not None

def test_suppressed_next_batch_enqueue_failure_logs_structured_context(monkeypatch):
    batch = SimpleNamespace(id="next-batch", status="running")
    pending_job = SimpleNamespace(
        id="job-1",
        video_id="video-1",
        celery_task_id=None,
        status="pending",
    )
    db = FakeDB(batches=[batch], pending_jobs=[pending_job])
    logs = []

    monkeypatch.setattr(
        channel_dispatcher,
        "_queue_channel_job",
        lambda _db, _job: (_ for _ in ()).throw(
            PipelineEnqueueError("job-1", RuntimeError("broker offline"))
        ),
    )
    monkeypatch.setattr(
        channel_dispatcher.logger,
        "warning",
        lambda event, **fields: logs.append((event, fields)),
    )

    dispatched = channel_dispatcher._dispatch_first_pending_job(
        db,
        batch,
        suppress_enqueue_error=True,
        source_batch_id="current-batch",
    )

    assert dispatched is None
    assert db.events == ["commit"]
    assert logs[0][0] == "channel_batch_advance_enqueue_failed"
    assert logs[0][1]["boundary"] == "channel_dispatcher.next_batch_enqueue"
    assert logs[0][1]["category"] == "best_effort_side_effect"
    assert logs[0][1]["batch_id"] == "current-batch"
    assert logs[0][1]["next_batch_id"] == "next-batch"
    assert logs[0][1]["next_job_id"] == "job-1"
    assert logs[0][1]["exception_type"] == "PipelineEnqueueError"
    assert logs[0][1]["outcome"] == "caller_continued"
