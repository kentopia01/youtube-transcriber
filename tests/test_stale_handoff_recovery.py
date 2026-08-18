from __future__ import annotations

import uuid

import pytest

from app.models.job import Job
from app.models.video import Video
from app.services import pipeline_resume
from app.services import stale_handoff_recovery as mod
from app.services.pipeline_enqueue import PipelineEnqueueError


class _Db:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _job(stage: str, *, metadata=None) -> Job:
    return Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        job_type="pipeline",
        status="running",
        current_stage=stage,
        last_artifact_check_result=metadata,
    )


def _video(job: Job, status: str = "transcribed") -> Video:
    return Video(
        id=job.video_id,
        youtube_video_id="abcdefghijk",
        url="https://youtube.test/watch?v=abcdefghijk",
        title="Test",
        status=status,
    )


def test_forward_artifact_progress_recovers_same_attempt(monkeypatch):
    job = _job("transcribe")
    video = _video(job)
    monkeypatch.setattr(
        mod,
        "detect_resume_point_sync",
        lambda db, video: (
            "tasks.cleanup_transcript",
            {"has_transcription": True, "selected_resume_stage": "tasks.cleanup_transcript"},
        ),
    )

    plan = mod.recover_stale_handoff(
        _Db(), job, video, publish=lambda: "requeued-task-id"
    )

    assert plan.recover is True
    assert plan.start_from == "tasks.cleanup_transcript"
    assert job.id == job.id  # same-attempt recovery; no replacement job
    assert job.status == "queued"
    assert job.celery_task_id == "requeued-task-id"
    assert job.last_artifact_check_result["stale_handoff_recovery_count"] == 1


def test_recovery_limit_converges_to_no_recovery(monkeypatch):
    job = _job("transcribe", metadata={"stale_handoff_recovery_count": 1})
    video = _video(job)
    monkeypatch.setattr(mod.settings, "pipeline_stale_handoff_recovery_limit", 1)

    plan = mod.plan_stale_handoff_recovery(_Db(), job, video)

    assert plan.recover is False
    assert plan.reason == "recovery_limit_reached"


def test_no_forward_artifact_progress_does_not_requeue(monkeypatch):
    job = _job("cleanup")
    video = _video(job)
    monkeypatch.setattr(
        mod,
        "detect_resume_point_sync",
        lambda db, video: ("tasks.cleanup_transcript", {"has_transcription": True}),
    )

    plan = mod.plan_stale_handoff_recovery(_Db(), job, video)

    assert plan.recover is False
    assert plan.reason == "no_forward_artifact_progress"


def test_publish_failure_leaves_visible_failed_attempt(monkeypatch):
    job = _job("summarize")
    video = _video(job, status="summarized")
    monkeypatch.setattr(
        mod,
        "detect_resume_point_sync",
        lambda db, video: (
            "tasks.generate_embeddings",
            {"has_summary": True, "selected_resume_stage": "tasks.generate_embeddings"},
        ),
    )

    with pytest.raises(PipelineEnqueueError):
        mod.recover_stale_handoff(
            _Db(),
            job,
            video,
            publish=lambda: (_ for _ in ()).throw(ConnectionError("redis down")),
        )

    assert job.status == "failed"
    assert "Failed to enqueue pipeline task" in job.error_message


def test_cleaned_video_resumes_at_summarize(monkeypatch):
    video = Video(
        id=uuid.uuid4(),
        youtube_video_id="abcdefghijk",
        url="https://youtube.test/watch?v=abcdefghijk",
        title="Cleaned",
        status="cleaned",
    )
    monkeypatch.setattr(pipeline_resume.os.path, "exists", lambda path: False)

    stage, result = pipeline_resume._build_resume_result(
        video,
        has_embeddings=False,
        has_summary=False,
        has_transcription=True,
    )

    assert stage == "tasks.summarize_transcription"
    assert result["selected_resume_stage"] == stage
