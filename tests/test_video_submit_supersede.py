import uuid
from types import SimpleNamespace

import pytest

from app.models.job import Job
from app.models.video import Video
from app.routers import videos as videos_router
from app.schemas.video import VideoSubmit


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
    def __init__(self, execute_results):
        self.execute_results = list(execute_results)
        self.added = []
        self.commit_calls = 0

    async def execute(self, statement):
        return _FakeResult(self.execute_results.pop(0))

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if hasattr(obj, "id") and getattr(obj, "id") is None:
                obj.id = uuid.uuid4()

    async def commit(self):
        self.commit_calls += 1


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
    )
    older_failed_2 = Job(
        id=uuid.uuid4(),
        video_id=video_id,
        job_type="pipeline",
        status="failed",
    )

    db = _FakeDB([existing, [older_failed_1, older_failed_2]])

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
    monkeypatch.setattr(videos_router, "run_pipeline", lambda _: "celery-123")

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
    assert replacement_job.celery_task_id == "celery-123"

    for superseded in (older_failed_1, older_failed_2):
        assert superseded.hidden_from_queue is True
        assert superseded.hidden_reason == "superseded"
        assert superseded.hidden_at is not None
        assert superseded.superseded_by_job_id == replacement_job.id


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
        lambda _: (_ for _ in ()).throw(AssertionError("run_pipeline should not be called")),
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
