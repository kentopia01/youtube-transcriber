from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.batch import Batch
from app.services.operations_dashboard import classify_batch_warning


@dataclass(frozen=True)
class BatchReconciliation:
    batch_id: str
    reason: str
    previous_status: str
    status: str
    completed_videos: int
    failed_videos: int
    total_videos: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


async def reconcile_stale_batches(
    db: AsyncSession,
    *,
    apply: bool = False,
    now: datetime | None = None,
) -> list[BatchReconciliation]:
    """Preview or close stale derived batch state without touching child jobs."""
    now = now or datetime.now(UTC)
    batches = (
        await db.execute(
            select(Batch)
            .options(selectinload(Batch.jobs))
            .where(Batch.status.in_(["pending", "running"]))
            .order_by(Batch.created_at, Batch.batch_number)
        )
    ).scalars().all()

    changes: list[BatchReconciliation] = []
    for batch in batches:
        warning = classify_batch_warning(batch, now=now)
        if warning is None:
            continue

        jobs = list(batch.jobs or ())
        completed = sum(job.status == "completed" for job in jobs)
        total = max(int(batch.total_videos or 0), len(jobs))
        failed = max(0, total - completed)
        status = "failed" if not jobs else ("completed_with_errors" if failed else "completed")
        changes.append(
            BatchReconciliation(
                batch_id=str(batch.id),
                reason=warning.reason,
                previous_status=batch.status,
                status=status,
                completed_videos=completed,
                failed_videos=failed,
                total_videos=total,
            )
        )
        if apply:
            batch.status = status
            batch.completed_videos = completed
            batch.failed_videos = failed
            batch.completed_at = now

    if apply and changes:
        await db.commit()
    return changes


__all__ = ["BatchReconciliation", "reconcile_stale_batches"]
