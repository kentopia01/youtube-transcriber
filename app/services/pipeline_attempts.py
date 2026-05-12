from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.job import Job
from app.services.pipeline_recovery import get_retry_block_reason
from app.services.pipeline_state import PIPELINE_ATTEMPT_ACTIVE_STATUSES, set_pipeline_job_state

ACTIVE_PIPELINE_ATTEMPT_STATUSES = PIPELINE_ATTEMPT_ACTIVE_STATUSES
ACTIVE_PIPELINE_ATTEMPT_UNIQUE_INDEX = "uq_jobs_pipeline_one_active_attempt"

ATTEMPT_RESULT_READY = "ready"
ATTEMPT_RESULT_CREATED = "created"
ATTEMPT_RESULT_ALREADY_ACTIVE = "already_active"
ATTEMPT_RESULT_BLOCKED = "blocked"
ATTEMPT_RESULT_ERROR = "error"

ProgressMessage = str | Callable[[int], str]


@dataclass(slots=True)
class PipelineAttemptAllocation:
    """Pre-create allocation result for one pipeline attempt."""

    status: str
    video_id: uuid.UUID
    latest_job: Job | None = None
    active_job: Job | None = None
    attempt_number: int | None = None
    reason: str | None = None

    @property
    def ready(self) -> bool:
        return self.status == ATTEMPT_RESULT_READY


@dataclass(slots=True)
class PipelineAttemptCreateResult:
    """Result of shared pipeline attempt creation."""

    status: str
    video_id: uuid.UUID
    job: Job | None = None
    latest_job: Job | None = None
    active_job: Job | None = None
    attempt_number: int | None = None
    reason: str | None = None

    @property
    def created(self) -> bool:
        return self.status == ATTEMPT_RESULT_CREATED



def is_active_pipeline_attempt_conflict(error: IntegrityError) -> bool:
    """Return True when an IntegrityError is the active-attempt unique-index violation."""
    orig = getattr(error, "orig", None)
    constraint_name = getattr(orig, "constraint_name", None)
    if constraint_name == ACTIVE_PIPELINE_ATTEMPT_UNIQUE_INDEX:
        return True

    diag = getattr(orig, "diag", None)
    if getattr(diag, "constraint_name", None) == ACTIVE_PIPELINE_ATTEMPT_UNIQUE_INDEX:
        return True

    return ACTIVE_PIPELINE_ATTEMPT_UNIQUE_INDEX in str(orig or error)


async def get_active_pipeline_attempt(db: AsyncSession, video_id: uuid.UUID) -> Job | None:
    """Return the latest active pipeline attempt for a video, if any."""
    result = await db.execute(
        select(Job)
        .where(
            Job.video_id == video_id,
            Job.job_type == "pipeline",
            Job.status.in_(ACTIVE_PIPELINE_ATTEMPT_STATUSES),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_latest_pipeline_attempt(db: AsyncSession, video_id: uuid.UUID) -> Job | None:
    """Return the latest pipeline attempt (active or terminal) for a video."""
    result = await db.execute(
        select(Job)
        .where(
            Job.video_id == video_id,
            Job.job_type == "pipeline",
        )
        .order_by(Job.attempt_number.desc(), Job.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def get_active_pipeline_attempt_sync(db: Session, video_id: uuid.UUID) -> Job | None:
    """Synchronous equivalent of :func:`get_active_pipeline_attempt`."""
    return (
        db.query(Job)
        .filter(
            Job.video_id == video_id,
            Job.job_type == "pipeline",
            Job.status.in_(ACTIVE_PIPELINE_ATTEMPT_STATUSES),
        )
        .order_by(Job.created_at.desc())
        .first()
    )


def get_latest_pipeline_attempt_sync(db: Session, video_id: uuid.UUID) -> Job | None:
    """Synchronous equivalent of :func:`get_latest_pipeline_attempt`."""
    return (
        db.query(Job)
        .filter(
            Job.video_id == video_id,
            Job.job_type == "pipeline",
        )
        .order_by(Job.attempt_number.desc(), Job.created_at.desc())
        .first()
    )


def _attempt_number_after(latest_job: Job | None) -> int:
    return ((latest_job.attempt_number if latest_job else 0) or 0) + 1


def _allocation_from_parts(
    *,
    video_id: uuid.UUID,
    active_job: Job | None,
    latest_job: Job | None,
    block_manual_review: bool,
) -> PipelineAttemptAllocation:
    if active_job is not None:
        return PipelineAttemptAllocation(
            status=ATTEMPT_RESULT_ALREADY_ACTIVE,
            video_id=video_id,
            latest_job=latest_job,
            active_job=active_job,
            attempt_number=getattr(active_job, "attempt_number", None),
            reason="active_attempt_exists",
        )

    if block_manual_review:
        retry_block_reason = get_retry_block_reason(latest_job)
        if retry_block_reason:
            return PipelineAttemptAllocation(
                status=ATTEMPT_RESULT_BLOCKED,
                video_id=video_id,
                latest_job=latest_job,
                reason=retry_block_reason,
            )

    return PipelineAttemptAllocation(
        status=ATTEMPT_RESULT_READY,
        video_id=video_id,
        latest_job=latest_job,
        attempt_number=_attempt_number_after(latest_job),
    )


async def allocate_pipeline_attempt_async(
    db: AsyncSession,
    video_id: uuid.UUID,
    *,
    block_manual_review: bool = True,
) -> PipelineAttemptAllocation:
    """Allocate attempt number after applying active/manual-review guards."""
    active_job = await get_active_pipeline_attempt(db, video_id)
    latest_job = active_job or await get_latest_pipeline_attempt(db, video_id)
    return _allocation_from_parts(
        video_id=video_id,
        active_job=active_job,
        latest_job=latest_job,
        block_manual_review=block_manual_review,
    )


def allocate_pipeline_attempt_sync(
    db: Session,
    video_id: uuid.UUID,
    *,
    block_manual_review: bool = True,
) -> PipelineAttemptAllocation:
    """Synchronous allocation for script/task paths."""
    active_job = get_active_pipeline_attempt_sync(db, video_id)
    latest_job = active_job or get_latest_pipeline_attempt_sync(db, video_id)
    return _allocation_from_parts(
        video_id=video_id,
        active_job=active_job,
        latest_job=latest_job,
        block_manual_review=block_manual_review,
    )


def _result_from_allocation(allocation: PipelineAttemptAllocation) -> PipelineAttemptCreateResult | None:
    if allocation.ready:
        return None

    return PipelineAttemptCreateResult(
        status=allocation.status,
        video_id=allocation.video_id,
        latest_job=allocation.latest_job,
        active_job=allocation.active_job,
        attempt_number=allocation.attempt_number,
        reason=allocation.reason,
    )


def _resolve_progress_message(progress_message: ProgressMessage, attempt_number: int) -> str:
    if callable(progress_message):
        return progress_message(attempt_number)
    return progress_message


def _build_pipeline_attempt_job(
    allocation: PipelineAttemptAllocation,
    *,
    status: str,
    current_stage: str,
    progress_message: ProgressMessage,
    attempt_creation_reason: str,
    channel_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    supersedes_job_id: uuid.UUID | None = None,
    supersede_latest: bool = True,
    last_artifact_check_result: dict | None = None,
) -> Job:
    if not allocation.ready or allocation.attempt_number is None:
        raise ValueError("Pipeline attempt allocation is not ready")

    resolved_supersedes_job_id = supersedes_job_id
    if resolved_supersedes_job_id is None and supersede_latest and allocation.latest_job is not None:
        resolved_supersedes_job_id = allocation.latest_job.id

    job = Job(
        video_id=allocation.video_id,
        channel_id=channel_id,
        batch_id=batch_id,
        job_type="pipeline",
        status=status,
        attempt_number=allocation.attempt_number,
        supersedes_job_id=resolved_supersedes_job_id,
        attempt_creation_reason=attempt_creation_reason,
        last_artifact_check_result=last_artifact_check_result,
    )
    set_pipeline_job_state(
        job,
        lifecycle_status=status,
        current_stage=current_stage,
        progress_pct=0.0,
        progress_message=_resolve_progress_message(progress_message, allocation.attempt_number),
        error_message=None,
        started_at=None,
        completed_at=None,
    )
    return job


async def _active_conflict_result_async(
    db: AsyncSession,
    *,
    video_id: uuid.UUID,
    latest_job: Job | None,
) -> PipelineAttemptCreateResult:
    active_job = await get_active_pipeline_attempt(db, video_id)
    if active_job is not None:
        return PipelineAttemptCreateResult(
            status=ATTEMPT_RESULT_ALREADY_ACTIVE,
            video_id=video_id,
            latest_job=latest_job,
            active_job=active_job,
            attempt_number=getattr(active_job, "attempt_number", None),
            reason="active_attempt_exists",
        )

    return PipelineAttemptCreateResult(
        status=ATTEMPT_RESULT_ERROR,
        video_id=video_id,
        latest_job=latest_job,
        reason="active_attempt_conflict_without_loaded_attempt",
    )


def _active_conflict_result_sync(
    db: Session,
    *,
    video_id: uuid.UUID,
    latest_job: Job | None,
) -> PipelineAttemptCreateResult:
    active_job = get_active_pipeline_attempt_sync(db, video_id)
    if active_job is not None:
        return PipelineAttemptCreateResult(
            status=ATTEMPT_RESULT_ALREADY_ACTIVE,
            video_id=video_id,
            latest_job=latest_job,
            active_job=active_job,
            attempt_number=getattr(active_job, "attempt_number", None),
            reason="active_attempt_exists",
        )

    return PipelineAttemptCreateResult(
        status=ATTEMPT_RESULT_ERROR,
        video_id=video_id,
        latest_job=latest_job,
        reason="active_attempt_conflict_without_loaded_attempt",
    )


async def create_pipeline_attempt_from_allocation_async(
    db: AsyncSession,
    allocation: PipelineAttemptAllocation,
    *,
    status: str,
    current_stage: str,
    progress_message: ProgressMessage,
    attempt_creation_reason: str,
    channel_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    supersedes_job_id: uuid.UUID | None = None,
    supersede_latest: bool = True,
    last_artifact_check_result: dict | None = None,
) -> PipelineAttemptCreateResult:
    """Create and flush a pipeline attempt from a shared allocation."""
    allocation_result = _result_from_allocation(allocation)
    if allocation_result is not None:
        return allocation_result

    job = _build_pipeline_attempt_job(
        allocation,
        status=status,
        current_stage=current_stage,
        progress_message=progress_message,
        attempt_creation_reason=attempt_creation_reason,
        channel_id=channel_id,
        batch_id=batch_id,
        supersedes_job_id=supersedes_job_id,
        supersede_latest=supersede_latest,
        last_artifact_check_result=last_artifact_check_result,
    )
    begin_nested = getattr(db, "begin_nested", None)
    try:
        if begin_nested is None:
            # Test-double fallback. Real AsyncSession paths use a savepoint below
            # so one active-attempt race cannot roll back earlier batch/job work.
            db.add(job)
            await db.flush()
        else:
            async with begin_nested():
                db.add(job)
                await db.flush()
    except IntegrityError as exc:
        if not is_active_pipeline_attempt_conflict(exc):
            raise
        if begin_nested is None:
            await db.rollback()
        return await _active_conflict_result_async(
            db,
            video_id=allocation.video_id,
            latest_job=allocation.latest_job,
        )

    return PipelineAttemptCreateResult(
        status=ATTEMPT_RESULT_CREATED,
        video_id=allocation.video_id,
        job=job,
        latest_job=allocation.latest_job,
        attempt_number=allocation.attempt_number,
    )


async def create_pipeline_attempt_async(
    db: AsyncSession,
    *,
    video_id: uuid.UUID,
    status: str,
    current_stage: str,
    progress_message: ProgressMessage,
    attempt_creation_reason: str,
    block_manual_review: bool = True,
    channel_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    supersedes_job_id: uuid.UUID | None = None,
    supersede_latest: bool = True,
    last_artifact_check_result: dict | None = None,
) -> PipelineAttemptCreateResult:
    """Allocate and create a pipeline attempt using the shared contract."""
    allocation = await allocate_pipeline_attempt_async(
        db,
        video_id,
        block_manual_review=block_manual_review,
    )
    return await create_pipeline_attempt_from_allocation_async(
        db,
        allocation,
        status=status,
        current_stage=current_stage,
        progress_message=progress_message,
        attempt_creation_reason=attempt_creation_reason,
        channel_id=channel_id,
        batch_id=batch_id,
        supersedes_job_id=supersedes_job_id,
        supersede_latest=supersede_latest,
        last_artifact_check_result=last_artifact_check_result,
    )


def create_pipeline_attempt_from_allocation_sync(
    db: Session,
    allocation: PipelineAttemptAllocation,
    *,
    status: str,
    current_stage: str,
    progress_message: ProgressMessage,
    attempt_creation_reason: str,
    channel_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    supersedes_job_id: uuid.UUID | None = None,
    supersede_latest: bool = True,
    last_artifact_check_result: dict | None = None,
) -> PipelineAttemptCreateResult:
    """Sync create/flush equivalent used by scripts and task helpers."""
    allocation_result = _result_from_allocation(allocation)
    if allocation_result is not None:
        return allocation_result

    job = _build_pipeline_attempt_job(
        allocation,
        status=status,
        current_stage=current_stage,
        progress_message=progress_message,
        attempt_creation_reason=attempt_creation_reason,
        channel_id=channel_id,
        batch_id=batch_id,
        supersedes_job_id=supersedes_job_id,
        supersede_latest=supersede_latest,
        last_artifact_check_result=last_artifact_check_result,
    )
    begin_nested = getattr(db, "begin_nested", None)
    try:
        if begin_nested is None:
            # Test-double fallback. Real Session paths use a savepoint below
            # so one active-attempt race cannot roll back earlier batch/job work.
            db.add(job)
            db.flush()
        else:
            with begin_nested():
                db.add(job)
                db.flush()
    except IntegrityError as exc:
        if not is_active_pipeline_attempt_conflict(exc):
            raise
        if begin_nested is None:
            db.rollback()
        return _active_conflict_result_sync(
            db,
            video_id=allocation.video_id,
            latest_job=allocation.latest_job,
        )

    return PipelineAttemptCreateResult(
        status=ATTEMPT_RESULT_CREATED,
        video_id=allocation.video_id,
        job=job,
        latest_job=allocation.latest_job,
        attempt_number=allocation.attempt_number,
    )


def create_pipeline_attempt_sync(
    db: Session,
    *,
    video_id: uuid.UUID,
    status: str,
    current_stage: str,
    progress_message: ProgressMessage,
    attempt_creation_reason: str,
    block_manual_review: bool = True,
    channel_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    supersedes_job_id: uuid.UUID | None = None,
    supersede_latest: bool = True,
    last_artifact_check_result: dict | None = None,
) -> PipelineAttemptCreateResult:
    """Sync allocate+create helper for shared attempt semantics."""
    allocation = allocate_pipeline_attempt_sync(
        db,
        video_id,
        block_manual_review=block_manual_review,
    )
    return create_pipeline_attempt_from_allocation_sync(
        db,
        allocation,
        status=status,
        current_stage=current_stage,
        progress_message=progress_message,
        attempt_creation_reason=attempt_creation_reason,
        channel_id=channel_id,
        batch_id=batch_id,
        supersedes_job_id=supersedes_job_id,
        supersede_latest=supersede_latest,
        last_artifact_check_result=last_artifact_check_result,
    )
