from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable

from app.models.job import Job
from app.services.pipeline_recovery import is_pipeline_job_stale

LONG_RUNNING_STAGES = {"transcribe", "diarize"}


def job_is_busy_but_healthy(job: Job, now: datetime | None = None) -> bool:
    if job.job_type != "pipeline" or job.status not in {"pending", "queued", "running"}:
        return False

    if job.current_stage not in LONG_RUNNING_STAGES:
        return False

    if now is None:
        now = datetime.now(UTC)

    anchor = job.current_stage_started_at or job.last_activity_at or job.started_at or job.created_at
    if anchor is None:
        return False
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)

    if is_pipeline_job_stale(job, now=now):
        return False

    return True


def any_busy_healthy_jobs(jobs: Iterable[Job], now: datetime | None = None) -> bool:
    return any(job_is_busy_but_healthy(job, now=now) for job in jobs)
