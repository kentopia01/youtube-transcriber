"""Read-only completion-SLA summary for autonomous pipeline attempts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.job import Job
from app.services.pipeline_observability import ATTEMPT_REASON_AUTO_INGEST
from app.services.pipeline_recovery import is_pipeline_job_stale


MAX_OUTCOME_DETAILS = 10


@dataclass(slots=True)
class PipelineOutcomeJob:
    job_id: str
    video_id: str | None
    youtube_video_id: str | None
    title: str
    status: str
    stage: str | None
    attempt_number: int
    failure_signature_count: int
    recovery_status: str | None
    error_message: str | None


@dataclass(slots=True)
class PipelineOutcomeSummary:
    since: str
    window_hours: float
    total: int
    completed: int
    failed: int
    active: int
    overdue: int
    failure_threshold: int
    degraded: bool
    failed_job_ids: list[str]
    overdue_job_ids: list[str]
    failed_jobs: list[PipelineOutcomeJob]
    overdue_jobs: list[PipelineOutcomeJob]

    def as_dict(self) -> dict:
        return asdict(self)


def _job_detail(job: Job) -> PipelineOutcomeJob:
    video = getattr(job, "video", None)
    title = str(getattr(video, "title", "") or "Untitled")
    return PipelineOutcomeJob(
        job_id=str(job.id),
        video_id=str(job.video_id) if job.video_id else None,
        youtube_video_id=getattr(video, "youtube_video_id", None),
        title=title,
        status=str(job.status),
        stage=job.current_stage,
        attempt_number=int(job.attempt_number or 1),
        failure_signature_count=int(job.failure_signature_count or 0),
        recovery_status=job.recovery_status,
        error_message=job.error_message,
    )


def collect_pipeline_outcomes(
    db: Session,
    *,
    hours: float = 24.0,
    failure_threshold: int = 2,
    now: datetime | None = None,
) -> PipelineOutcomeSummary:
    now = now or datetime.now(UTC)
    since = now - timedelta(hours=hours)
    recent_jobs = (
        db.query(Job)
        .filter(
            Job.job_type == "pipeline",
            Job.created_at >= since,
        )
        .order_by(Job.created_at.desc())
        .all()
    )

    # The cohort is videos that entered the window through autonomous ingest;
    # the reported state is each video's actual latest attempt. Retry reason and
    # queue visibility are presentation/history fields, not outcome filters.
    auto_video_ids = {
        job.video_id
        for job in recent_jobs
        if job.video_id is not None
        and job.attempt_creation_reason == ATTEMPT_REASON_AUTO_INGEST
    }
    latest_by_video: dict[object, Job] = {}
    for job in recent_jobs:
        if job.video_id not in auto_video_ids:
            continue
        previous = latest_by_video.get(job.video_id)
        if previous is None or (
            int(job.attempt_number or 1),
            job.created_at or datetime.min.replace(tzinfo=UTC),
        ) > (
            int(previous.attempt_number or 1),
            previous.created_at or datetime.min.replace(tzinfo=UTC),
        ):
            latest_by_video[job.video_id] = job

    jobs = sorted(
        latest_by_video.values(),
        key=lambda job: job.created_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    completed = [job for job in jobs if job.status == "completed"]
    failed = [job for job in jobs if job.status == "failed"]
    active = [job for job in jobs if job.status in {"pending", "queued", "running"}]
    overdue = [job for job in active if is_pipeline_job_stale(job, now=now)]
    degraded = len(failed) >= failure_threshold or bool(overdue)
    return PipelineOutcomeSummary(
        since=since.isoformat(),
        window_hours=hours,
        total=len(jobs),
        completed=len(completed),
        failed=len(failed),
        active=len(active),
        overdue=len(overdue),
        failure_threshold=failure_threshold,
        degraded=degraded,
        failed_job_ids=[str(job.id) for job in failed[:25]],
        overdue_job_ids=[str(job.id) for job in overdue[:25]],
        failed_jobs=[_job_detail(job) for job in failed[:MAX_OUTCOME_DETAILS]],
        overdue_jobs=[_job_detail(job) for job in overdue[:MAX_OUTCOME_DETAILS]],
    )
