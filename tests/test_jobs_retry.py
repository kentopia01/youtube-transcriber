import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.job import Job
from app.models.video import Video
from app.routers import jobs as jobs_router


class _FakeScalars:
    def __init__(self, value):
        self.value = value

    def all(self):
        if isinstance(self.value, list):
            return self.value
        if self.value is None:
            return []
        return [self.value]


class _FakeResult:
    def __init__(self, obj):
        self.obj = obj

    def scalar_one_or_none(self):
        return self.obj

    def scalars(self):
        return _FakeScalars(self.obj)


class _FakeDB:
    def __init__(self, results):
        self.results = list(results)
        self.added = []
        self.committed = False

    async def execute(self, statement):
        return _FakeResult(self.results.pop(0))

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if isinstance(obj, Job) and obj.id is None:
                obj.id = uuid.uuid4()

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_retry_job_creates_new_pipeline_job_and_hides_superseded_failures(monkeypatch):
    job = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        job_type="pipeline",
        status="failed",
        progress_pct=60.0,
    )
    older_failed = Job(
        id=uuid.uuid4(),
        video_id=job.video_id,
        channel_id=job.channel_id,
        job_type="pipeline",
        status="failed",
        progress_pct=20.0,
    )
    video = Video(
        id=job.video_id,
        youtube_video_id="dQw4w9WgXcQ",
        title="Test",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        status="failed",
        error_message="failed",
    )
    # Results: job, video, None (active job check), then 3x None for
    # _detect_resume_point checks, then failed jobs to supersede.
    db = _FakeDB([job, video, None, None, None, None, [job, older_failed]])

    monkeypatch.setattr(
        jobs_router,
        "run_pipeline_from",
        lambda video_id, start_from: "celery-123",
    )

    response = await jobs_router.retry_job(job.id, SimpleNamespace(headers={}), db)

    assert response["status"] == "queued"
    assert response["video_id"] == str(video.id)
    assert response["job_id"]
    assert db.committed is True

    assert video.status == "pending"
    assert video.error_message is None

    assert len(db.added) == 1
    retried_job = db.added[0]
    assert retried_job.status == "queued"
    assert "retry" in retried_job.progress_message.lower()
    assert retried_job.celery_task_id == "celery-123"

    for superseded in (job, older_failed):
        assert superseded.hidden_from_queue is True
        assert superseded.hidden_reason == "superseded"
        assert superseded.hidden_at is not None
        assert superseded.superseded_by_job_id == retried_job.id


@pytest.mark.asyncio
async def test_retry_job_returns_existing_active_retry(monkeypatch):
    job = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        job_type="pipeline",
        status="failed",
        progress_pct=10.0,
    )
    video = Video(
        id=job.video_id,
        youtube_video_id="dQw4w9WgXcQ",
        title="Test",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        status="failed",
        error_message="failed",
    )
    existing = Job(
        id=uuid.uuid4(),
        video_id=job.video_id,
        job_type="pipeline",
        status="running",
        progress_pct=42.0,
    )

    db = _FakeDB([job, video, existing])

    monkeypatch.setattr(
        jobs_router,
        "run_pipeline_from",
        lambda video_id, start_from: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    response = await jobs_router.retry_job(job.id, SimpleNamespace(headers={}), db)

    assert response == {
        "status": "running",
        "job_id": str(existing.id),
        "video_id": str(video.id),
    }
    assert db.added == []


@pytest.mark.asyncio
async def test_retry_job_rejects_non_failed_jobs():
    job = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        job_type="pipeline",
        status="completed",
        progress_pct=100.0,
    )
    db = _FakeDB([job])

    with pytest.raises(HTTPException) as exc:
        await jobs_router.retry_job(job.id, SimpleNamespace(headers={}), db)

    assert exc.value.status_code == 400
    assert "failed jobs" in str(exc.value.detail)
