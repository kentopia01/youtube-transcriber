import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.job import Job
from app.models.video import Video
from app.routers import jobs as jobs_router


class _FakeResult:
    def __init__(self, obj):
        self.obj = obj

    def scalar_one_or_none(self):
        return self.obj


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
async def test_retry_job_creates_new_pipeline_job(monkeypatch):
    job = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        job_type="pipeline",
        status="failed",
        progress_pct=60.0,
    )
    video = Video(
        id=job.video_id,
        youtube_video_id="dQw4w9WgXcQ",
        title="Test",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        status="failed",
        error_message="failed",
    )
    db = _FakeDB([job, video])

    monkeypatch.setattr(jobs_router, "run_pipeline", lambda video_id: "celery-123")

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
    assert retried_job.progress_message == "Queued for retry"
    assert retried_job.celery_task_id == "celery-123"


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
