import uuid

import pytest
from celery.exceptions import Ignore

from app.models.job import Job
from app.models.video import Video
from app.tasks.helpers import build_pipeline_task_payload, get_pipeline_job_context


class _FakeActiveQuery:
    def __init__(self, active_job):
        self.active_job = active_job

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.active_job


class _FakeDB:
    def __init__(self, *, video, job, active_job=None):
        self.video = video
        self.job = job
        self.active_job = active_job if active_job is not None else job

    def get(self, model, value):
        if model is Video and value == self.video.id:
            return self.video
        if model is Job and value == self.job.id:
            return self.job
        return None

    def query(self, model):
        assert model is Job
        return _FakeActiveQuery(self.active_job)


def test_get_pipeline_job_context_accepts_exact_active_attempt():
    video_id = uuid.uuid4()
    job_id = uuid.uuid4()
    video = Video(id=video_id, youtube_video_id="abc123", title="Video", url="https://example.com")
    job = Job(id=job_id, video_id=video_id, job_type="pipeline", status="queued", current_stage="queued")
    db = _FakeDB(video=video, job=job)

    payload, resolved_video, resolved_job = get_pipeline_job_context(
        db,
        build_pipeline_task_payload(video_id, job_id),
        expected_stage="download",
    )

    assert payload == {"video_id": str(video_id), "job_id": str(job_id)}
    assert resolved_video is video
    assert resolved_job is job


def test_get_pipeline_job_context_ignores_superseded_attempt():
    video_id = uuid.uuid4()
    job_id = uuid.uuid4()
    active_id = uuid.uuid4()
    video = Video(id=video_id, youtube_video_id="abc123", title="Video", url="https://example.com")
    stale_job = Job(id=job_id, video_id=video_id, job_type="pipeline", status="queued", current_stage="queued")
    active_job = Job(id=active_id, video_id=video_id, job_type="pipeline", status="running", current_stage="download")
    db = _FakeDB(video=video, job=stale_job, active_job=active_job)

    with pytest.raises(Ignore):
        get_pipeline_job_context(
            db,
            build_pipeline_task_payload(video_id, job_id),
            expected_stage="download",
        )


def test_get_pipeline_job_context_ignores_stage_that_is_already_past_expected():
    video_id = uuid.uuid4()
    job_id = uuid.uuid4()
    video = Video(id=video_id, youtube_video_id="abc123", title="Video", url="https://example.com")
    job = Job(id=job_id, video_id=video_id, job_type="pipeline", status="running", current_stage="embed")
    db = _FakeDB(video=video, job=job)

    with pytest.raises(Ignore):
        get_pipeline_job_context(
            db,
            build_pipeline_task_payload(video_id, job_id),
            expected_stage="summarize",
        )
