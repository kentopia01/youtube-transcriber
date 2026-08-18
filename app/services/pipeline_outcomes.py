"""Read-only completion-SLA summary for autonomous pipeline attempts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.job import Job
from app.services.pipeline_observability import ATTEMPT_REASON_AUTO_INGEST
from app.services.pipeline_recovery import is_pipeline_job_stale


@dataclass(slots=True)
class PipelineOutcomeSummary:
    since: str
    total: int
    completed: int
    failed: int
    active: int
    overdue: int
    failure_threshold: int
    degraded: bool
    failed_job_ids: list[str]
    overdue_job_ids: list[str]

    def as_dict(self) -> dict:
        return asdict(self)


def collect_pipeline_outcomes(
    db: Session,
    *,
    hours: float = 24.0,
    failure_threshold: int = 2,
    now: datetime | None = None,
) -> PipelineOutcomeSummary:
    now = now or datetime.now(UTC)
    since = now - timedelta(hours=hours)
    jobs = (
        db.query(Job)
        .filter(
            Job.job_type == "pipeline",
            Job.attempt_creation_reason == ATTEMPT_REASON_AUTO_INGEST,
            Job.created_at >= since,
        )
        .order_by(Job.created_at.desc())
        .all()
    )
    completed = [job for job in jobs if job.status == "completed"]
    failed = [job for job in jobs if job.status == "failed" and not job.hidden_from_queue]
    active = [job for job in jobs if job.status in {"pending", "queued", "running"}]
    overdue = [job for job in active if is_pipeline_job_stale(job, now=now)]
    degraded = len(failed) >= failure_threshold or bool(overdue)
    return PipelineOutcomeSummary(
        since=since.isoformat(),
        total=len(jobs),
        completed=len(completed),
        failed=len(failed),
        active=len(active),
        overdue=len(overdue),
        failure_threshold=failure_threshold,
        degraded=degraded,
        failed_job_ids=[str(job.id) for job in failed[:25]],
        overdue_job_ids=[str(job.id) for job in overdue[:25]],
    )
