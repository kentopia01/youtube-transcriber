import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from fastapi import HTTPException

from app.models.job import Job
from app.models.video import Video
from app.routers import videos as videos_router
from app.schemas.video import VideoSubmit
from app.services.pipeline_observability import ATTEMPT_REASON_MANUAL_RESUBMIT, ATTEMPT_REASON_VIDEO_SUBMIT
from app.services.pipeline_recovery import MANUAL_REVIEW_RECOVERY_STATUS


class _FakeScalars:
    def __init__(self, value):
        self.value = value

    def all(self):
        if isinstance(self.value, list):
            return self.value
        if self.value is None:
            return []
        return [self.value]

    def first(self):
        if isinstance(self.value, list):
            return self.value[0] if self.value else None
        return self.value


class _FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return _FakeScalars(self.value)


class _FakeDB:
    def __init__(self, execute_results, *, flush_error=None):
        self.execute_results = list(execute_results)
        self.added = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self.flush_error = flush_error

    async def execute(self, statement):
        return _FakeResult(self.execute_results.pop(0))

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        if self.flush_error is not None:
            flush_error, self.flush_error = self.flush_error, None
            raise flush_error

        for obj in self.added:
            if hasattr(obj, "id") and getattr(obj, "id") is None:
                obj.id = uuid.uuid4()

    async def commit(self):
        self.commit_calls += 1

    async def rollback(self):
        self.rollback_calls += 1


async def _fake_get_or_create_channel(*args, **kwargs):
    return None


@pytest.mark.asyncio
async def test_resubmit_failed_video_hides_prior_failed_jobs(monkeypatch):
    video_id = uuid.uuid4()
    existing = Video(
        id=video_id,
        youtube_video_id="dQw4w9WgXcQ",
        title="Old title",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        status="failed",
        error_message="boom",
    )

    older_failed_1 = Job(
        id=uuid.uuid4(),
        video_id=video_id,
        job_type="pipeline",
        status="failed",
        attempt_number=1,
    )
    older_failed_2 = Job(
        id=uuid.uuid4(),
        video_id=video_id,
        job_type="pipeline",
        status="failed",
        attempt_number=2,
    )

    db = _FakeDB([existing, None, older_failed_2, [older_failed_1, older_failed_2]])

    monkeypatch.setattr(videos_router, "extract_video_id", lambda _: "dQw4w9WgXcQ")
    monkeypatch.setattr(
        videos_router,
        "get_video_info",
        lambda _: {
            "video_id": "dQw4w9WgXcQ",
            "title": "Updated title",
            "description": "Updated description",
            "duration": 42,
            "thumbnail": "https://example.com/thumb.jpg",
            "channel_id": None,
            "channel_name": None,
            "channel_url": None,
            "published_at": "20260401",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        },
    )
    monkeypatch.setattr(videos_router, "get_or_create_channel", _fake_get_or_create_channel)
    monkeypatch.setattr(videos_router, "run_pipeline", lambda _, job_id=None: "celery-123")

    result = await videos_router.submit_video(
        SimpleNamespace(),
        VideoSubmit(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        db,
    )

    assert result["status"] == "queued"
    assert result["video_id"] == str(video_id)

    assert existing.status == "pending"
    assert existing.error_message is None

    assert len(db.added) == 1
    replacement_job = db.added[0]
    assert replacement_job.status == "queued"
    assert replacement_job.current_stage == "queued"
    assert replacement_job.celery_task_id == "celery-123"
    assert replacement_job.attempt_number == 3
    assert replacement_job.supersedes_job_id == older_failed_2.id
    assert replacement_job.attempt_creation_reason == ATTEMPT_REASON_MANUAL_RESUBMIT

    for superseded in (older_failed_1, older_failed_2):
        assert superseded.hidden_from_queue is True
        assert superseded.hidden_reason == "superseded"
        assert superseded.hidden_at is not None
        assert superseded.superseded_by_job_id == replacement_job.id


@pytest.mark.asyncio
async def test_resubmit_failed_video_reuses_existing_active_attempt(monkeypatch):
    video_id = uuid.uuid4()
    existing = Video(
        id=video_id,
        youtube_video_id="dQw4w9WgXcQ",
        title="Old title",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        status="failed",
        error_message="boom",
    )
    active_job = Job(
        id=uuid.uuid4(),
        video_id=video_id,
        job_type="pipeline",
        status="queued",
        attempt_number=4,
    )

    db = _FakeDB([existing, active_job])

    monkeypatch.setattr(videos_router, "extract_video_id", lambda _: "dQw4w9WgXcQ")
    monkeypatch.setattr(
        videos_router,
        "get_video_info",
        lambda _: {
            "video_id": "dQw4w9WgXcQ",
            "title": "Updated title",
            "description": "Updated description",
            "duration": 42,
            "thumbnail": "https://example.com/thumb.jpg",
            "channel_id": None,
            "channel_name": None,
            "channel_url": None,
            "published_at": "20260401",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        },
    )
    monkeypatch.setattr(videos_router, "get_or_create_channel", _fake_get_or_create_channel)
    monkeypatch.setattr(
        videos_router,
        "run_pipeline",
        lambda _, job_id=None: (_ for _ in ()).throw(AssertionError("run_pipeline should not be called")),
    )

    result = await videos_router.submit_video(
        SimpleNamespace(),
        VideoSubmit(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        db,
    )

    assert result == {
        "job_id": str(active_job.id),
        "video_id": str(video_id),
        "status": "existing",
    }
    assert db.added == []


@pytest.mark.asyncio
async def test_resubmit_failed_video_returns_existing_attempt_on_db_active_conflict(monkeypatch):
    video_id = uuid.uuid4()
    existing = Video(
        id=video_id,
        youtube_video_id="dQw4w9WgXcQ",
        title="Old title",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        status="failed",
        error_message="boom",
    )
    latest_failed = Job(
        id=uuid.uuid4(),
        video_id=video_id,
        job_type="pipeline",
        status="failed",
        attempt_number=4,
    )
    active_attempt = Job(
        id=uuid.uuid4(),
        video_id=video_id,
        job_type="pipeline",
        status="queued",
        attempt_number=5,
    )

    db = _FakeDB(
        [existing, None, latest_failed, active_attempt],
        flush_error=IntegrityError(
            "INSERT INTO jobs ...",
            {},
            Exception(
                'duplicate key value violates unique constraint "uq_jobs_pipeline_one_active_attempt"'
            ),
        ),
    )

    monkeypatch.setattr(videos_router, "extract_video_id", lambda _: "dQw4w9WgXcQ")
    monkeypatch.setattr(
        videos_router,
        "get_video_info",
        lambda _: {
            "video_id": "dQw4w9WgXcQ",
            "title": "Updated title",
            "description": "Updated description",
            "duration": 42,
            "thumbnail": "https://example.com/thumb.jpg",
            "channel_id": None,
            "channel_name": None,
            "channel_url": None,
            "published_at": "20260401",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        },
    )
    monkeypatch.setattr(videos_router, "get_or_create_channel", _fake_get_or_create_channel)
    monkeypatch.setattr(
        videos_router,
        "run_pipeline",
        lambda _, job_id=None: (_ for _ in ()).throw(AssertionError("run_pipeline should not be called")),
    )

    result = await videos_router.submit_video(
        SimpleNamespace(),
        VideoSubmit(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        db,
    )

    assert result == {
        "job_id": str(active_attempt.id),
        "video_id": str(video_id),
        "status": "existing",
    }
    assert db.rollback_calls == 1


@pytest.mark.asyncio
async def test_resubmit_failed_video_blocks_manual_review_retry(monkeypatch):
    video_id = uuid.uuid4()
    existing = Video(
        id=video_id,
        youtube_video_id="dQw4w9WgXcQ",
        title="Old title",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        status="failed",
        error_message="boom",
    )
    latest_failed = Job(
        id=uuid.uuid4(),
        video_id=video_id,
        job_type="pipeline",
        status="failed",
        attempt_number=3,
        recovery_status=MANUAL_REVIEW_RECOVERY_STATUS,
        recovery_reason="Manual review required after repeated failures.",
    )

    db = _FakeDB([existing, None, latest_failed])

    monkeypatch.setattr(videos_router, "extract_video_id", lambda _: "dQw4w9WgXcQ")
    monkeypatch.setattr(
        videos_router,
        "get_video_info",
        lambda _: {
            "video_id": "dQw4w9WgXcQ",
            "title": "Updated title",
            "description": "Updated description",
            "duration": 42,
            "thumbnail": "https://example.com/thumb.jpg",
            "channel_id": None,
            "channel_name": None,
            "channel_url": None,
            "published_at": "20260401",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        },
    )
    monkeypatch.setattr(videos_router, "get_or_create_channel", _fake_get_or_create_channel)

    with pytest.raises(HTTPException) as exc:
        await videos_router.submit_video(
            SimpleNamespace(),
            VideoSubmit(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            db,
        )

    assert exc.value.status_code == 409
    assert "Manual review required" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_submit_new_video_sets_operator_action_attempt_reason(monkeypatch):
    db = _FakeDB([None, None, None])

    monkeypatch.setattr(videos_router, "extract_video_id", lambda _: "dQw4w9WgXcQ")
    monkeypatch.setattr(
        videos_router,
        "get_video_info",
        lambda _: {
            "video_id": "dQw4w9WgXcQ",
            "title": "Brand New",
            "description": "Fresh submit",
            "duration": 88,
            "thumbnail": "https://example.com/thumb.jpg",
            "channel_id": None,
            "channel_name": None,
            "channel_url": None,
            "published_at": "20260401",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        },
    )
    monkeypatch.setattr(videos_router, "get_or_create_channel", _fake_get_or_create_channel)
    monkeypatch.setattr(videos_router, "run_pipeline", lambda _video_id, job_id=None: "celery-new")

    result = await videos_router.submit_video(
        SimpleNamespace(),
        VideoSubmit(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        db,
    )

    assert result["status"] == "queued"

    new_job = next(obj for obj in db.added if isinstance(obj, Job))
    assert new_job.attempt_creation_reason == ATTEMPT_REASON_VIDEO_SUBMIT
    assert new_job.celery_task_id == "celery-new"


@pytest.mark.asyncio
async def test_submit_existing_non_failed_video_keeps_dedupe_behavior(monkeypatch):
    video_id = uuid.uuid4()
    existing = Video(
        id=video_id,
        youtube_video_id="dQw4w9WgXcQ",
        title="Existing",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        status="completed",
        error_message=None,
    )
    latest_job = Job(
        id=uuid.uuid4(),
        video_id=video_id,
        job_type="pipeline",
        status="completed",
        progress_pct=100.0,
    )
    unrelated_failed = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        job_type="pipeline",
        status="failed",
        hidden_from_queue=False,
    )

    db = _FakeDB([existing, latest_job])

    monkeypatch.setattr(videos_router, "extract_video_id", lambda _: "dQw4w9WgXcQ")
    monkeypatch.setattr(
        videos_router,
        "get_video_info",
        lambda _: {
            "video_id": "dQw4w9WgXcQ",
            "title": "Refreshed title",
            "description": "Refreshed description",
            "duration": 123,
            "thumbnail": "https://example.com/thumb.jpg",
            "channel_id": None,
            "channel_name": None,
            "channel_url": None,
            "published_at": "20260401",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        },
    )
    monkeypatch.setattr(videos_router, "get_or_create_channel", _fake_get_or_create_channel)
    monkeypatch.setattr(
        videos_router,
        "run_pipeline",
        lambda _, job_id=None: (_ for _ in ()).throw(AssertionError("run_pipeline should not be called")),
    )

    result = await videos_router.submit_video(
        SimpleNamespace(),
        VideoSubmit(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        db,
    )

    assert result == {
        "job_id": str(latest_job.id),
        "video_id": str(video_id),
        "status": "existing",
    }
    assert existing.status == "completed"
    assert db.commit_calls == 1
    assert db.added == []
    assert unrelated_failed.hidden_from_queue is False
