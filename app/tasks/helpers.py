"""Shared helpers for pipeline task files."""

import uuid

from sqlalchemy.orm import Session

from app.models.job import Job
from app.services.pipeline_state import set_pipeline_job_state

_SENTINEL = object()


def get_latest_pipeline_job(db: Session, video_id: uuid.UUID) -> Job | None:
    """Return the most recent pipeline job for a video.

    Tasks must update the LATEST job so that retries (which create new Job
    records) get the progress updates instead of the original failed job.
    """
    return (
        db.query(Job)
        .filter(Job.video_id == video_id, Job.job_type == "pipeline")
        .order_by(Job.created_at.desc())
        .first()
    )


def update_pipeline_job(
    job: Job | None,
    *,
    lifecycle_status: str | None = None,
    current_stage: str | None | object = _SENTINEL,
    progress_pct: float | object = _SENTINEL,
    progress_message: str | None | object = _SENTINEL,
    error_message: str | None | object = _SENTINEL,
    started_at=_SENTINEL,
    completed_at=_SENTINEL,
) -> None:
    """Safely apply a state transition when a pipeline job exists."""
    if not job:
        return

    kwargs = {}
    if lifecycle_status is not None:
        kwargs["lifecycle_status"] = lifecycle_status
    if current_stage is not _SENTINEL:
        kwargs["current_stage"] = current_stage
    if progress_pct is not _SENTINEL:
        kwargs["progress_pct"] = progress_pct
    if progress_message is not _SENTINEL:
        kwargs["progress_message"] = progress_message
    if error_message is not _SENTINEL:
        kwargs["error_message"] = error_message
    if started_at is not _SENTINEL:
        kwargs["started_at"] = started_at
    if completed_at is not _SENTINEL:
        kwargs["completed_at"] = completed_at

    set_pipeline_job_state(job, **kwargs)
