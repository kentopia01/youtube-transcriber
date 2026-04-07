import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job


async def hide_superseded_failed_jobs(
    db: AsyncSession,
    *,
    video_id: uuid.UUID,
    superseded_by_job_id: uuid.UUID,
) -> int:
    """Hide failed pipeline jobs for a video once a newer replacement job exists."""
    result = await db.execute(
        select(Job).where(
            Job.video_id == video_id,
            Job.job_type == "pipeline",
            Job.status == "failed",
            Job.hidden_from_queue.is_(False),
            Job.id != superseded_by_job_id,
        )
    )
    superseded_jobs = result.scalars().all()
    if not superseded_jobs:
        return 0

    hidden_at = datetime.now(timezone.utc)
    for superseded in superseded_jobs:
        superseded.hidden_from_queue = True
        superseded.hidden_reason = "superseded"
        superseded.hidden_at = hidden_at
        superseded.superseded_by_job_id = superseded_by_job_id

    return len(superseded_jobs)
