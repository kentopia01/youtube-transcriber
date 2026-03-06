"""Shared helpers for pipeline task files."""

import uuid

from sqlalchemy.orm import Session

from app.models.job import Job


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
