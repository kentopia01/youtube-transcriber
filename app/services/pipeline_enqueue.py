from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.job import Job
from app.services.pipeline_state import PIPELINE_STAGE_QUEUED, set_pipeline_job_state


class PipelineEnqueueError(RuntimeError):
    """Raised after a pipeline job could not be published to Celery.

    By the time this is raised, the helper has made a best-effort attempt to
    mark the job failed so operators can see and retry the stranded enqueue.
    """

    def __init__(self, job_id: str, original: BaseException):
        super().__init__(f"Failed to enqueue pipeline job {job_id}: {original}")
        self.job_id = job_id
        self.original = original


def _record_enqueue_failure(job: Job, exc: BaseException) -> None:
    error = f"Failed to enqueue pipeline task: {type(exc).__name__}: {exc}"
    set_pipeline_job_state(
        job,
        lifecycle_status="failed",
        current_stage=PIPELINE_STAGE_QUEUED,
        progress_message="Pipeline enqueue failed before Celery accepted the task",
        error_message=error,
        started_at=None,
    )
    job.celery_task_id = None


def enqueue_pipeline_job_after_commit(
    db: Session,
    job: Job,
    *,
    publish: Callable[[], str],
) -> str:
    """Commit queued job state, then publish Celery work, then persist task id.

    This is the sync boundary used by channel dispatch and task-layer batch
    advancement. The contract is intentionally narrow: callers prepare a job in
    queued state, this helper commits that state before Celery can consume the
    payload, then stores the returned Celery id in a follow-up commit.
    """

    job_id = str(job.id)
    db.commit()

    try:
        celery_task_id = publish()
    except Exception as exc:  # noqa: BLE001 - publish can fail in broker-specific ways
        _record_enqueue_failure(job, exc)
        try:
            db.commit()
        except Exception:  # noqa: BLE001 - preserve the original enqueue failure
            db.rollback()
        raise PipelineEnqueueError(job_id, exc) from exc

    job.celery_task_id = celery_task_id
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return celery_task_id


async def enqueue_pipeline_job_after_commit_async(
    db: AsyncSession,
    job: Job,
    *,
    publish: Callable[[], str],
) -> str:
    """Async version of :func:`enqueue_pipeline_job_after_commit`."""

    job_id = str(job.id)
    await db.commit()

    try:
        celery_task_id = publish()
    except Exception as exc:  # noqa: BLE001 - publish can fail in broker-specific ways
        _record_enqueue_failure(job, exc)
        try:
            await db.commit()
        except Exception:  # noqa: BLE001 - preserve the original enqueue failure
            await db.rollback()
        raise PipelineEnqueueError(job_id, exc) from exc

    job.celery_task_id = celery_task_id
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return celery_task_id
