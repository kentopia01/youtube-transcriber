import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.job import Job
from app.models.video import Video
from app.routers import jobs as jobs_router
from app.services.pipeline_observability import ATTEMPT_REASON_STALE_RECOVERY, ATTEMPT_REASON_USER_RETRY
from app.services.pipeline_recovery import MANUAL_REVIEW_RECOVERY_STATUS, STALE_REAP_RECOVERY_STATUS


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
    def __init__(self, results, *, flush_error=None):
        self.results = list(results)
        self.added = []
        self.committed = False
        self.rolled_back = False
        self.flush_error = flush_error

    async def execute(self, statement):
        return _FakeResult(self.results.pop(0))

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        if self.flush_error is not None:
            flush_error, self.flush_error = self.flush_error, None
            raise flush_error

        for obj in self.added:
            if isinstance(obj, Job) and obj.id is None:
                obj.id = uuid.uuid4()

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


@pytest.mark.asyncio
async def test_retry_job_creates_new_pipeline_job_and_hides_superseded_failures(monkeypatch):
    job = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        job_type="pipeline",
        status="failed",
        attempt_number=2,
        progress_pct=60.0,
    )
    older_failed = Job(
        id=uuid.uuid4(),
        video_id=job.video_id,
        channel_id=job.channel_id,
        job_type="pipeline",
        status="failed",
        attempt_number=1,
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
    # Results: job, video, None (active attempt check), latest attempt,
    # then 3x None for artifact checks, then failed jobs to supersede.
    db = _FakeDB([job, video, None, job, None, None, None, [job, older_failed]])

    monkeypatch.setattr(
        jobs_router,
        "run_pipeline_from",
        lambda video_id, start_from, job_id=None: "celery-123",
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
    assert retried_job.current_stage == "queued"
    assert "retry" in retried_job.progress_message.lower()
    assert retried_job.celery_task_id == "celery-123"
    assert retried_job.attempt_number == 3
    assert retried_job.supersedes_job_id == job.id
    assert retried_job.attempt_creation_reason == ATTEMPT_REASON_USER_RETRY
    assert retried_job.last_artifact_check_result["selected_resume_stage"] == "tasks.download_audio"

    for superseded in (job, older_failed):
        assert superseded.hidden_from_queue is True
        assert superseded.hidden_reason == "superseded"
        assert superseded.hidden_at is not None
        assert superseded.superseded_by_job_id == retried_job.id


@pytest.mark.asyncio
async def test_retry_job_from_stale_reaped_attempt_sets_stale_recovery_reason(monkeypatch):
    job = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        job_type="pipeline",
        status="failed",
        attempt_number=4,
        recovery_status=STALE_REAP_RECOVERY_STATUS,
    )
    video = Video(
        id=job.video_id,
        youtube_video_id="dQw4w9WgXcQ",
        title="Test",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        status="failed",
        error_message="failed",
    )
    db = _FakeDB([job, video, None, job, None, None, None, [job]])

    monkeypatch.setattr(
        jobs_router,
        "run_pipeline_from",
        lambda video_id, start_from, job_id=None: "celery-stale",
    )

    response = await jobs_router.retry_job(job.id, SimpleNamespace(headers={}), db)

    assert response["status"] == "queued"
    retried_job = db.added[0]
    assert retried_job.attempt_creation_reason == ATTEMPT_REASON_STALE_RECOVERY


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
        lambda video_id, start_from, job_id=None: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    response = await jobs_router.retry_job(job.id, SimpleNamespace(headers={}), db)

    assert response == {
        "status": "running",
        "job_id": str(existing.id),
        "video_id": str(video.id),
    }
    assert db.added == []


@pytest.mark.asyncio
async def test_retry_job_returns_existing_pending_attempt(monkeypatch):
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
        status="pending",
        progress_pct=0.0,
    )

    db = _FakeDB([job, video, existing])

    monkeypatch.setattr(
        jobs_router,
        "run_pipeline_from",
        lambda video_id, start_from, job_id=None: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    response = await jobs_router.retry_job(job.id, SimpleNamespace(headers={}), db)

    assert response == {
        "status": "pending",
        "job_id": str(existing.id),
        "video_id": str(video.id),
    }
    assert db.added == []


@pytest.mark.asyncio
async def test_retry_job_returns_existing_attempt_when_db_active_index_is_hit(monkeypatch):
    job = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        job_type="pipeline",
        status="failed",
        attempt_number=1,
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
    active_attempt = Job(
        id=uuid.uuid4(),
        video_id=job.video_id,
        job_type="pipeline",
        status="queued",
        attempt_number=2,
        progress_pct=0.0,
    )

    db = _FakeDB(
        [job, video, None, job, None, None, None, active_attempt],
        flush_error=IntegrityError(
            "INSERT INTO jobs ...",
            {},
            Exception(
                'duplicate key value violates unique constraint "uq_jobs_pipeline_one_active_attempt"'
            ),
        ),
    )

    monkeypatch.setattr(
        jobs_router,
        "run_pipeline_from",
        lambda video_id, start_from, job_id=None: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    response = await jobs_router.retry_job(job.id, SimpleNamespace(headers={}), db)

    assert response == {
        "status": "queued",
        "job_id": str(active_attempt.id),
        "video_id": str(video.id),
    }
    assert db.rolled_back is True
    assert db.committed is False


@pytest.mark.asyncio
async def test_retry_job_blocks_manual_review_failures():
    job = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        job_type="pipeline",
        status="failed",
        recovery_status=MANUAL_REVIEW_RECOVERY_STATUS,
        recovery_reason="Manual review required after repeated failures.",
    )
    db = _FakeDB([job])

    with pytest.raises(HTTPException) as exc:
        await jobs_router.retry_job(job.id, SimpleNamespace(headers={}), db)

    assert exc.value.status_code == 409
    assert "Manual review required" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_retry_job_blocks_when_latest_attempt_requires_manual_review():
    requested_job = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        job_type="pipeline",
        status="failed",
        attempt_number=1,
    )
    latest_attempt = Job(
        id=uuid.uuid4(),
        video_id=requested_job.video_id,
        channel_id=requested_job.channel_id,
        job_type="pipeline",
        status="failed",
        attempt_number=2,
        recovery_status=MANUAL_REVIEW_RECOVERY_STATUS,
        recovery_reason="Manual review required after repeated failures.",
    )
    video = Video(
        id=requested_job.video_id,
        youtube_video_id="dQw4w9WgXcQ",
        title="Test",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        status="failed",
        error_message="failed",
    )
    db = _FakeDB([requested_job, video, None, latest_attempt])

    with pytest.raises(HTTPException) as exc:
        await jobs_router.retry_job(requested_job.id, SimpleNamespace(headers={}), db)

    assert exc.value.status_code == 409
    assert "Manual review required" in str(exc.value.detail)


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


def test_select_resume_stage_avoids_diarize_when_audio_is_missing():
    stage = jobs_router._select_resume_stage(
        has_embeddings=False,
        has_summary=False,
        has_transcription=True,
        has_audio=False,
        diarization_requires_audio=True,
    )

    assert stage == "tasks.download_audio"


def test_select_resume_stage_uses_transcribe_when_audio_exists_but_transcript_missing():
    stage = jobs_router._select_resume_stage(
        has_embeddings=False,
        has_summary=False,
        has_transcription=False,
        has_audio=True,
        diarization_requires_audio=True,
    )

    assert stage == "tasks.transcribe_audio"


def test_select_resume_stage_skips_diarize_when_not_required():
    stage = jobs_router._select_resume_stage(
        has_embeddings=False,
        has_summary=False,
        has_transcription=True,
        has_audio=False,
        diarization_requires_audio=False,
    )

    assert stage == "tasks.cleanup_transcript"
