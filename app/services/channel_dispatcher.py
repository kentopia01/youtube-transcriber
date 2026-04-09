from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models.batch import Batch
from app.models.job import Job
from app.services.pipeline_observability import ATTEMPT_REASON_CHANNEL_PROCESS
from app.services.pipeline_state import PIPELINE_STAGE_QUEUED, set_pipeline_job_state
from app.tasks.pipeline import run_pipeline

sync_engine = create_engine(settings.database_url_sync)

CHANNEL_BATCH_PENDING = "pending"
CHANNEL_BATCH_RUNNING = "running"
CHANNEL_BATCH_DONE = {"completed", "completed_with_errors"}
CHANNEL_JOB_ACTIVE = {"queued", "running"}
CHANNEL_JOB_TERMINAL = {"completed", "failed", "cancelled"}
CHANNEL_ACTIVE_LIMIT = 1


def _active_manual_jobs_exist(db: Session) -> bool:
    return (
        db.query(Job)
        .filter(
            Job.job_type == "pipeline",
            Job.status.in_(CHANNEL_JOB_ACTIVE),
            Job.attempt_creation_reason != ATTEMPT_REASON_CHANNEL_PROCESS,
        )
        .first()
        is not None
    )


def _active_channel_jobs_count(db: Session) -> int:
    return (
        db.query(Job)
        .filter(
            Job.job_type == "pipeline",
            Job.attempt_creation_reason == ATTEMPT_REASON_CHANNEL_PROCESS,
            Job.status.in_(CHANNEL_JOB_ACTIVE),
        )
        .count()
    )


def _earliest_dispatchable_job(db: Session) -> tuple[Batch | None, Job | None]:
    batches = (
        db.query(Batch)
        .filter(Batch.status.in_([CHANNEL_BATCH_RUNNING, CHANNEL_BATCH_PENDING]))
        .order_by(Batch.created_at.asc(), Batch.batch_number.asc())
        .all()
    )
    for batch in batches:
        job = (
            db.query(Job)
            .filter(
                Job.batch_id == batch.id,
                Job.job_type == "pipeline",
                Job.attempt_creation_reason == ATTEMPT_REASON_CHANNEL_PROCESS,
                Job.status == "pending",
            )
            .order_by(Job.created_at.asc())
            .first()
        )
        if job is not None:
            return batch, job
    return None, None


def promote_pending_channel_jobs(db: Session, limit: int = CHANNEL_ACTIVE_LIMIT) -> list[str]:
    if _active_manual_jobs_exist(db):
        return []

    promoted: list[str] = []
    while _active_channel_jobs_count(db) < limit:
        batch, job = _earliest_dispatchable_job(db)
        if not batch or not job:
            break

        if batch.status == CHANNEL_BATCH_PENDING:
            batch.status = CHANNEL_BATCH_RUNNING

        set_pipeline_job_state(
            job,
            lifecycle_status="queued",
            current_stage=PIPELINE_STAGE_QUEUED,
            progress_pct=0.0,
            progress_message="Queued by channel dispatcher",
        )
        job.celery_task_id = run_pipeline(str(job.video_id), job_id=str(job.id))
        promoted.append(str(job.id))
        db.flush()

    return promoted


def refresh_batch_progress(db: Session, batch_id) -> Batch | None:
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
        batch.status = "completed" if failed == 0 else "completed_with_errors"
        batch.completed_at = datetime.now(UTC)
    elif terminal > 0 or completed > 0 or failed > 0:
        batch.status = CHANNEL_BATCH_RUNNING

    return batch


def update_batch_progress_and_dispatch(db: Session, batch_id) -> list[str]:
    refresh_batch_progress(db, batch_id)
    return promote_pending_channel_jobs(db)


def dispatch_channel_backlog(
    db: Session | None = None,
    limit: int = CHANNEL_ACTIVE_LIMIT,
    *,
    max_jobs: int | None = None,
) -> list[str]:
    resolved_limit = max_jobs if max_jobs is not None else limit

    if db is not None:
        return promote_pending_channel_jobs(db, limit=resolved_limit)

    with Session(sync_engine) as db:
        promoted = promote_pending_channel_jobs(db, limit=resolved_limit)
        if promoted:
            db.commit()
        return promoted
