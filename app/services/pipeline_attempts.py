import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.services.pipeline_state import PIPELINE_ATTEMPT_ACTIVE_STATUSES

ACTIVE_PIPELINE_ATTEMPT_STATUSES = PIPELINE_ATTEMPT_ACTIVE_STATUSES
ACTIVE_PIPELINE_ATTEMPT_UNIQUE_INDEX = "uq_jobs_pipeline_one_active_attempt"


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
