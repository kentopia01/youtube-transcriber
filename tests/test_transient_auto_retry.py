import uuid
from datetime import UTC, datetime, timedelta

from app.models.job import Job
from app.models.video import Video
from app.services import transient_auto_retry as mod
from app.services.pipeline_attempts import (
    ATTEMPT_RESULT_ALREADY_ACTIVE,
    ATTEMPT_RESULT_READY,
    PipelineAttemptAllocation,
)
from app.services.pipeline_recovery import MANUAL_REVIEW_RECOVERY_STATUS


def _job(
    *,
    stage="cleanup",
    exc="APIConnectionError",
    message="connection error.",
    signature_count=1,
    completed_at=None,
):
    now = datetime.now(UTC)
    return Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        job_type="pipeline",
        status="failed",
        current_stage=stage,
        failure_signature=f"{stage}|{exc}|{message}",
        failure_signature_count=signature_count,
        attempt_number=1,
        completed_at=completed_at or now,
        last_activity_at=completed_at or now,
        created_at=completed_at or now,
    )


class _FakeQuery:
    def __init__(self, jobs):
        self.jobs = list(jobs)

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self.jobs)

    def first(self):
        return self.jobs[0] if self.jobs else None


class _FakeDB:
    def __init__(self, jobs, *, videos=None):
        self.jobs = jobs
        self.videos = videos or {}
        self.added = []
        self.commits = 0
        self.events = []

    def query(self, _model):
        return _FakeQuery(self.jobs)

    def add(self, obj):
        self.added.append(obj)

    def get(self, model, key):
        if model is Video:
            return self.videos.get(key)
        return None

    def flush(self):
        for obj in self.added:
            if hasattr(obj, "id") and getattr(obj, "id") is None:
                obj.id = uuid.uuid4()

    def commit(self):
        self.commits += 1
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")


def test_failure_signature_match_is_limited_to_transient_cleanup_and_summarize():
    assert mod.failure_signature_is_known_transient("cleanup|APIConnectionError|connection error.")
    assert mod.failure_signature_is_known_transient("summarize|APITimeoutError|request timed out")
    assert mod.failure_signature_is_known_transient("summarize|RateLimitError|too many requests")

    assert not mod.failure_signature_is_known_transient("cleanup|BadRequestError|invalid request")
    assert not mod.failure_signature_is_known_transient("transcribe|APIConnectionError|connection error.")


def test_transient_retry_candidate_blocks_manual_review_failures():
    job = _job()
    job.recovery_status = MANUAL_REVIEW_RECOVERY_STATUS
    job.recovery_reason = "Manual review required"

    decision = mod.evaluate_transient_retry_candidate(
        job,
        latest_attempt=job,
        active_attempt=None,
    )

    assert decision.status == "skipped"
    assert decision.reason == "manual_review"


def test_transient_retry_candidate_blocks_retry_limit_reached(monkeypatch):
    monkeypatch.setattr(mod.settings, "pipeline_manual_review_after_failures", 2)
    job = _job(signature_count=2)

    decision = mod.evaluate_transient_retry_candidate(
        job,
        latest_attempt=job,
        active_attempt=None,
    )

    assert decision.status == "skipped"
    assert decision.reason == "retry_limit_reached"


def test_transient_retry_candidate_blocks_duplicate_active_attempt():
    job = _job()
    active = Job(
        id=uuid.uuid4(),
        video_id=job.video_id,
        job_type="pipeline",
        status="running",
    )

    decision = mod.evaluate_transient_retry_candidate(
        job,
        latest_attempt=job,
        active_attempt=active,
    )

    assert decision.status == "skipped"
    assert decision.reason == "active_attempt_exists"
    assert decision.active_job_id == str(active.id)


def test_transient_retry_candidate_blocks_old_failures():
    job = _job(completed_at=datetime.now(UTC) - timedelta(hours=30))

    decision = mod.evaluate_transient_retry_candidate(
        job,
        latest_attempt=job,
        active_attempt=None,
        max_age_hours=24,
    )

    assert decision.status == "skipped"
    assert decision.reason == "too_old"


def test_dry_run_sweep_plans_without_enqueueing(monkeypatch):
    job = _job()
    db = _FakeDB([job])
    monkeypatch.setattr(
        mod,
        "allocate_pipeline_attempt_sync",
        lambda _db, _video_id: PipelineAttemptAllocation(
            status=ATTEMPT_RESULT_READY,
            video_id=job.video_id,
            latest_job=job,
            attempt_number=2,
        ),
    )

    decisions = mod.retry_transient_failures(db, dry_run=True, limit=10)

    assert [(d.status, d.reason) for d in decisions] == [
        ("planned", "dry_run_known_transient_failure")
    ]
    assert db.added == []
    assert db.commits == 0


def test_sweep_skips_active_attempt_without_enqueueing(monkeypatch):
    job = _job()
    active = Job(id=uuid.uuid4(), video_id=job.video_id, job_type="pipeline", status="queued")
    db = _FakeDB([job])
    monkeypatch.setattr(
        mod,
        "allocate_pipeline_attempt_sync",
        lambda _db, _video_id: PipelineAttemptAllocation(
            status=ATTEMPT_RESULT_ALREADY_ACTIVE,
            video_id=job.video_id,
            latest_job=active,
            active_job=active,
            attempt_number=active.attempt_number,
            reason="active_attempt_exists",
        ),
    )
    monkeypatch.setattr(
        mod,
        "run_pipeline_from",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not enqueue")),
    )

    decisions = mod.retry_transient_failures(db, dry_run=False, limit=10)

    assert [(d.status, d.reason) for d in decisions] == [("skipped", "active_attempt_exists")]
    assert db.added == []
    assert db.commits == 0


def test_transient_retry_commits_before_publish(monkeypatch):
    job = _job()
    video = Video(
        id=job.video_id,
        youtube_video_id="dQw4w9WgXcQ",
        title="Transient",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        status="failed",
        error_message="failed",
    )
    db = _FakeDB([job], videos={job.video_id: video})

    monkeypatch.setattr(
        mod,
        "allocate_pipeline_attempt_sync",
        lambda _db, _video_id: PipelineAttemptAllocation(
            status=ATTEMPT_RESULT_READY,
            video_id=job.video_id,
            latest_job=job,
            attempt_number=2,
        ),
    )
    monkeypatch.setattr(
        mod,
        "detect_resume_point_sync",
        lambda _db, _video: ("tasks.cleanup_transcript", {"selected_resume_stage": "tasks.cleanup_transcript"}),
    )
    monkeypatch.setattr(mod, "hide_superseded_failed_jobs_sync", lambda *_args, **_kwargs: None)

    def _publish(_video_id, start_from, job_id=None):
        assert db.events == ["commit"]
        db.events.append("publish")
        return "celery-auto"

    monkeypatch.setattr(mod, "run_pipeline_from", _publish)

    decisions = mod.retry_transient_failures(db, dry_run=False, limit=10)

    assert [(d.status, d.reason) for d in decisions] == [("queued", "known_transient_failure")]
    retry_job = db.added[0]
    assert retry_job.celery_task_id == "celery-auto"
    assert retry_job.status == "queued"
    assert retry_job.attempt_number == 2
    assert db.events == ["commit", "publish", "commit"]
