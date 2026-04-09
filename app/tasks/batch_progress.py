from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.batch import Batch
from app.models.job import Job
from app.services.pipeline_state import PIPELINE_STAGE_QUEUED, set_pipeline_job_state
from app.tasks.pipeline import run_pipeline


def update_batch_progress_and_maybe_advance(db: Session, batch_id):
    """Refresh batch counters and start the next batch when current one is terminal."""
    batch = db.get(Batch, batch_id)
    if not batch:
        return

    jobs = db.query(Job).filter(Job.batch_id == batch.id).all()
    total_jobs = len(jobs)
    completed = sum(1 for j in jobs if j.status == "completed")
    failed = sum(1 for j in jobs if j.status == "failed")
    terminal = completed + failed

    batch.completed_videos = completed
    batch.failed_videos = failed

    if total_jobs == 0 or terminal < total_jobs:
        return

    if completed == 0 and failed > 0:
        batch.status = "failed"
    elif failed > 0:
        batch.status = "completed_with_errors"
    else:
        batch.status = "completed"
    batch.completed_at = datetime.now(UTC)

    next_batch = (
        db.query(Batch)
        .filter(
            Batch.channel_id == batch.channel_id,
            Batch.status == "pending",
            Batch.batch_number > batch.batch_number,
        )
        .order_by(Batch.batch_number.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if not next_batch:
        return

    next_batch.status = "running"
    next_jobs = db.query(Job).filter(Job.batch_id == next_batch.id).all()
    for job in next_jobs:
        if not job.video_id or job.celery_task_id:
            continue
        set_pipeline_job_state(
            job,
            lifecycle_status="queued",
            current_stage=PIPELINE_STAGE_QUEUED,
            progress_pct=0.0,
            progress_message="Queued for processing",
            error_message=None,
            started_at=None,
            completed_at=None,
        )
        job.celery_task_id = run_pipeline(str(job.video_id))
