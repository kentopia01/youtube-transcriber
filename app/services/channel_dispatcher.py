from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models.batch import Batch
from app.models.job import Job
from app.services.pipeline_enqueue import PipelineEnqueueError, enqueue_pipeline_job_after_commit
from app.services.pipeline_observability import ATTEMPT_REASON_CHANNEL_PROCESS
from app.services.pipeline_state import PIPELINE_STAGE_QUEUED, set_pipeline_job_state
from app.tasks.pipeline import run_pipeline

logger = structlog.get_logger()

SIDE_EFFECT_BEST_EFFORT = "best_effort_side_effect"
SIDE_EFFECT_BUG_MASK = "bug_mask_candidate"

sync_engine = create_engine(settings.database_url_sync)

CHANNEL_BATCH_PENDING = "pending"
CHANNEL_BATCH_RUNNING = "running"
CHANNEL_BATCH_DONE = {"completed", "completed_with_errors"}
CHANNEL_BATCH_TERMINAL = CHANNEL_BATCH_DONE | {"failed"}
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
        job = _find_first_pending_job(db, batch)
        if job is not None:
            return batch, job
    return None, None


def _batch_terminal_status(*, failed: int) -> str:
    """Return the canonical terminal status for a channel batch.

    A batch where every job failed/cancelled is still a completed channel batch
    with per-video errors, not a failed orchestration batch. Keeping this rule in
    the dispatcher prevents task-layer and sweep semantics from drifting.
    """
    return "completed_with_errors" if failed > 0 else "completed"


def _queue_channel_job(db: Session, job: Job) -> str:
    set_pipeline_job_state(
        job,
        lifecycle_status="queued",
        current_stage=PIPELINE_STAGE_QUEUED,
        progress_pct=0.0,
        progress_message="Queued by channel dispatcher",
    )
    video_id_str = str(job.video_id)
    job_id_str = str(job.id)
    enqueue_pipeline_job_after_commit(
        db,
        job,
        publish=lambda: run_pipeline(video_id_str, job_id=job_id_str),
    )
    return job_id_str


def _find_first_pending_job(db: Session, batch: Batch) -> Job | None:
    jobs = (
        db.query(Job)
        .filter(
            Job.batch_id == batch.id,
            Job.job_type == "pipeline",
            Job.attempt_creation_reason == ATTEMPT_REASON_CHANNEL_PROCESS,
            Job.status == CHANNEL_BATCH_PENDING,
        )
        .order_by(Job.created_at.asc())
        .all()
    )

    for job in jobs:
        if job.celery_task_id or not job.video_id:
            continue
        if job.status != CHANNEL_BATCH_PENDING:
            continue
        return job
    return None


def _dispatch_first_pending_job(
    db: Session,
    batch: Batch,
    *,
    suppress_enqueue_error: bool = False,
    source_batch_id: object | None = None,
) -> str | None:
    job = _find_first_pending_job(db, batch)
    if job is None:
        return None

    try:
        return _queue_channel_job(db, job)
    except PipelineEnqueueError as exc:
        if not suppress_enqueue_error:
            raise

        # Advancing the next batch is a side effect of the current pipeline task.
        # The enqueue helper has already committed an operator-visible failure on
        # the next job; keep that failure local to the next batch and do not let it
        # retry/reclassify the just-completed current pipeline job.
        logger.warning(
            "channel_batch_advance_enqueue_failed",
            boundary="channel_dispatcher.next_batch_enqueue",
            category=SIDE_EFFECT_BEST_EFFORT,
            batch_id=str(source_batch_id or ""),
            next_batch_id=str(getattr(batch, "id", "")),
            next_job_id=str(getattr(job, "id", "")),
            exception_type=exc.__class__.__name__,
            error_message=str(exc)[:500],
            outcome="caller_continued",
        )
        refresh_batch_progress(db, getattr(batch, "id", None))
        try:
            db.commit()
        except Exception as commit_exc:  # noqa: BLE001 - keep original pipeline task isolated
            db.rollback()
            logger.warning(
                "channel_batch_advance_progress_commit_failed",
                boundary="channel_dispatcher.next_batch_progress_refresh",
                category=SIDE_EFFECT_BUG_MASK,
                batch_id=str(source_batch_id or ""),
                next_batch_id=str(getattr(batch, "id", "")),
                next_job_id=str(getattr(job, "id", "")),
                exception_type=commit_exc.__class__.__name__,
                error_message=str(commit_exc)[:500],
                outcome="caller_continued",
            )
        return None


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


def promote_pending_channel_jobs(db: Session, limit: int = CHANNEL_ACTIVE_LIMIT) -> list[str]:
    """Promote pending channel jobs with a commit-before-publish boundary."""
    if _active_manual_jobs_exist(db):
        return []

    promoted: list[str] = []
    while _active_channel_jobs_count(db) < limit:
        batch, job = _earliest_dispatchable_job(db)
        if not batch or not job:
            break

        if batch.status == CHANNEL_BATCH_PENDING:
            batch.status = CHANNEL_BATCH_RUNNING

        promoted.append(_queue_channel_job(db, job))

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
        batch.status = _batch_terminal_status(failed=failed)
        batch.completed_at = datetime.now(UTC)
    elif terminal > 0 or completed > 0 or failed > 0:
        batch.status = CHANNEL_BATCH_RUNNING

    return batch


def update_batch_progress_and_maybe_advance(db: Session, batch_id) -> list[str]:
    """Refresh a batch and release the next batch when the current one is terminal."""
    batch = refresh_batch_progress(db, batch_id)
    if not batch:
        return []

    if batch.status not in CHANNEL_BATCH_TERMINAL:
        return []

    next_batch = _find_next_batch(db, batch)
    if not next_batch:
        return []

    next_batch.status = CHANNEL_BATCH_RUNNING
    dispatched = _dispatch_first_pending_job(
        db,
        next_batch,
        suppress_enqueue_error=True,
        source_batch_id=batch_id,
    )
    return [dispatched] if dispatched else []


def update_batch_progress_and_dispatch(db: Session, batch_id) -> list[str]:
    return update_batch_progress_and_maybe_advance(db, batch_id)


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
        return promote_pending_channel_jobs(db, limit=resolved_limit)
