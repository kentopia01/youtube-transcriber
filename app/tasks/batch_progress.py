from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.batch import Batch
from app.models.job import Job
from app.services.pipeline_observability import ATTEMPT_REASON_CHANNEL_PROCESS
from app.services.pipeline_state import PIPELINE_STAGE_QUEUED, set_pipeline_job_state
from app.tasks.pipeline import run_pipeline

CHANNEL_BATCH_PENDING = "pending"
CHANNEL_BATCH_RUNNING = "running"
CHANNEL_JOB_TERMINAL = {"completed", "failed", "cancelled"}


def _refresh_batch_progress(db: Session, batch_id) -> Batch | None:
    batch = db.get(Batch, batch_id)
    if not batch:
        return None

    jobs = db.query(Job).filter(Job.batch_id == batch_id).all()
    if not jobs:
        return batch

    total = len(jobs)
    completed = sum(1 for job in jobs if job.status == "completed")
    failed = sum(1 for job in jobs if job.status in {"failed", "cancelled"})
    terminal = sum(1 for job in jobs if job.status in CHANNEL_JOB_TERMINAL)

    batch.completed_videos = completed
    batch.failed_videos = failed

    if terminal == total:
        if completed == 0 and failed > 0:
            batch.status = "failed"
        elif failed > 0:
            batch.status = "completed_with_errors"
        else:
            batch.status = "completed"
        batch.completed_at = datetime.now(UTC)
    elif terminal > 0 or completed > 0 or failed > 0:
        batch.status = CHANNEL_BATCH_RUNNING

    return batch


def _find_next_batch(db: Session, batch: Batch) -> Batch | None:
    return (
        db.query(Batch)
        .filter(
            Batch.channel_id == batch.channel_id,
            Batch.status == CHANNEL_BATCH_PENDING,
            Batch.batch_number > batch.batch_number,
        )
        .order_by(Batch.batch_number.asc())
        .with_for_update()
        .first()
    )


def _dispatch_first_pending_job(db: Session, batch: Batch) -> str | None:
    jobs = (
        db.query(Job)
        .filter(
            Job.batch_id == batch.id,
            Job.job_type == "pipeline",
            Job.attempt_creation_reason == ATTEMPT_REASON_CHANNEL_PROCESS,
            Job.status == CHANNEL_BATCH_PENDING,
        )
        .all()
    )

    for job in jobs:
        if job.celery_task_id or not job.video_id:
            continue

        set_pipeline_job_state(
            job,
            lifecycle_status="queued",
            current_stage=PIPELINE_STAGE_QUEUED,
            progress_pct=0.0,
            progress_message="Queued by channel dispatcher",
        )
        job.celery_task_id = run_pipeline(str(job.video_id), job_id=str(job.id))
        return str(job.id)

    return None


def update_batch_progress_and_maybe_advance(db: Session, batch_id):
    """Refresh batch progress and, if terminal, release the next batch carefully.

    This task-layer helper intentionally keeps a small compatibility surface for the
    orchestration tests, even though the broader dispatcher logic now lives under
    `app.services.channel_dispatcher`.
    """
    batch = _refresh_batch_progress(db, batch_id)
    if not batch:
        return []

    if batch.status not in {"completed", "completed_with_errors", "failed"}:
        return []

    next_batch = _find_next_batch(db, batch)
    if not next_batch:
        return []

    next_batch.status = CHANNEL_BATCH_RUNNING
    dispatched = _dispatch_first_pending_job(db, next_batch)
    return [dispatched] if dispatched else []
