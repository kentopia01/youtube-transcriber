from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.batch import Batch
from app.models.channel import Channel
from app.models.channel_subscription import ChannelSubscription
from app.models.job import Job
from app.models.video import Video
from app.models.video_report import VideoReport
from app.services.pipeline_recovery import is_pipeline_job_stale
from app.services.worker_health import any_busy_healthy_jobs


REQUIRED_OPERATION_QUEUES = frozenset({"audio", "diarize", "post", "celery"})
ACTIVE_JOB_STATUSES = frozenset({"pending", "queued", "running"})
PENDING_JOB_STATUSES = frozenset({"pending", "queued"})
RECENT_COMPLETION_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class QueueCoverage:
    workers: tuple[str, ...]
    covered_queues: frozenset[str]
    required_queues: frozenset[str] = REQUIRED_OPERATION_QUEUES
    error_code: str | None = None

    @property
    def missing_queues(self) -> frozenset[str]:
        return self.required_queues - self.covered_queues

    @property
    def complete(self) -> bool:
        return bool(self.workers) and not self.missing_queues


@dataclass(frozen=True)
class QueueHealth:
    state: str
    label: str
    detail: str
    worker_count: int
    covered_queues: tuple[str, ...]
    missing_queues: tuple[str, ...]
    busy: bool
    error_code: str | None = None

    @property
    def css_status(self) -> str:
        return {
            "idle": "completed",
            "healthy": "completed",
            "busy": "running",
            "degraded": "running",
            "unavailable": "failed",
        }.get(self.state, "running")

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "label": self.label,
            "detail": self.detail,
            "worker_count": self.worker_count,
            "covered_queues": list(self.covered_queues),
            "missing_queues": list(self.missing_queues),
            "busy": self.busy,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class OperationsCounts:
    total_videos: int
    completed_videos: int
    total_channels: int
    active_jobs: int
    pending_jobs: int
    failed_visible_jobs: int
    recent_completions: int
    report_delivery_warnings: int
    subscription_warnings: int

    @property
    def in_flight_jobs(self) -> int:
        return self.active_jobs + self.pending_jobs

    def to_dict(self) -> dict[str, int]:
        return {
            "total_videos": self.total_videos,
            "completed_videos": self.completed_videos,
            "total_channels": self.total_channels,
            "active_jobs": self.active_jobs,
            "pending_jobs": self.pending_jobs,
            "in_flight_jobs": self.in_flight_jobs,
            "failed_visible_jobs": self.failed_visible_jobs,
            "recent_completions": self.recent_completions,
            "report_delivery_warnings": self.report_delivery_warnings,
            "subscription_warnings": self.subscription_warnings,
        }


@dataclass(frozen=True)
class BatchWarning:
    batch_id: str
    reason: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "batch_id": self.batch_id,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RuntimeCapabilities:
    transcription_engine: str
    transcription_label: str
    inline_diarization_enabled: bool
    transcript_cleanup_enabled: bool
    report_delivery_enabled: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "transcription_engine": self.transcription_engine,
            "transcription_label": self.transcription_label,
            "inline_diarization_enabled": self.inline_diarization_enabled,
            "transcript_cleanup_enabled": self.transcript_cleanup_enabled,
            "report_delivery_enabled": self.report_delivery_enabled,
        }


@dataclass(frozen=True)
class OperationsSummary:
    generated_at: datetime
    counts: OperationsCounts
    queue_health: QueueHealth
    runtime: RuntimeCapabilities
    active_batches: tuple[Batch, ...]
    batch_warnings: tuple[BatchWarning, ...]

    @property
    def batch_warning_map(self) -> dict[object, BatchWarning]:
        warnings = {warning.batch_id: warning for warning in self.batch_warnings}
        return {
            batch.id: warnings[str(batch.id)]
            for batch in self.active_batches
            if str(batch.id) in warnings
        }

    @property
    def warning_count(self) -> int:
        return (
            self.counts.failed_visible_jobs
            + self.counts.report_delivery_warnings
            + self.counts.subscription_warnings
            + len(self.batch_warnings)
        )

    def to_dict(self) -> dict[str, object]:
        warning_map = {warning.batch_id: warning for warning in self.batch_warnings}
        return {
            "generated_at": self.generated_at.isoformat(),
            "counts": self.counts.to_dict(),
            "queue_health": self.queue_health.to_dict(),
            "runtime": self.runtime.to_dict(),
            "active_batches": [
                {
                    "id": str(batch.id),
                    "status": batch.status,
                    "batch_number": batch.batch_number,
                    "total_batches": batch.total_batches,
                    "total_videos": batch.total_videos,
                    "completed_videos": batch.completed_videos,
                    "failed_videos": batch.failed_videos,
                    "warning": (
                        warning_map[str(batch.id)].to_dict()
                        if str(batch.id) in warning_map
                        else None
                    ),
                }
                for batch in self.active_batches
            ],
            "batch_warnings": [warning.to_dict() for warning in self.batch_warnings],
        }


def inspect_queue_coverage(
    *,
    timeout_seconds: float = 1.0,
    required_queues: frozenset[str] = REQUIRED_OPERATION_QUEUES,
) -> QueueCoverage:
    """Read live Celery queue coverage without mutating worker state."""
    try:
        from app.tasks.celery_app import celery

        queues_by_worker = celery.control.inspect(timeout=timeout_seconds).active_queues() or {}
    except Exception as exc:  # noqa: BLE001 - health must degrade instead of breaking the page
        return QueueCoverage(
            workers=(),
            covered_queues=frozenset(),
            required_queues=required_queues,
            error_code=exc.__class__.__name__,
        )

    covered: set[str] = set()
    for queues in queues_by_worker.values():
        for queue in queues or []:
            name = queue.get("name")
            if name:
                covered.add(str(name))

    return QueueCoverage(
        workers=tuple(sorted(str(worker) for worker in queues_by_worker)),
        covered_queues=frozenset(covered),
        required_queues=required_queues,
    )


def derive_queue_health(coverage: QueueCoverage, jobs: list[Job]) -> QueueHealth:
    running_jobs = [job for job in jobs if job.status == "running"]
    pending_jobs = [job for job in jobs if job.status in PENDING_JOB_STATUSES]
    busy_healthy = any_busy_healthy_jobs(jobs) if jobs else False
    covered = tuple(sorted(coverage.covered_queues))
    missing = tuple(sorted(coverage.missing_queues))

    if coverage.complete:
        if running_jobs:
            return QueueHealth(
                state="busy",
                label="Queue Busy",
                detail=f"{len(running_jobs)} running; all required queues covered.",
                worker_count=len(coverage.workers),
                covered_queues=covered,
                missing_queues=missing,
                busy=True,
            )
        if pending_jobs:
            return QueueHealth(
                state="healthy",
                label="Queue Ready",
                detail=f"{len(pending_jobs)} waiting; all required queues covered.",
                worker_count=len(coverage.workers),
                covered_queues=covered,
                missing_queues=missing,
                busy=False,
            )
        return QueueHealth(
            state="idle",
            label="Queue Idle",
            detail="Workers are online and all required queues are covered.",
            worker_count=len(coverage.workers),
            covered_queues=covered,
            missing_queues=missing,
            busy=False,
        )

    if coverage.workers or busy_healthy:
        progress_note = " Active work still shows recent progress." if busy_healthy else ""
        return QueueHealth(
            state="degraded",
            label="Queue Degraded",
            detail=f"Missing coverage: {', '.join(missing) or 'unknown'}.{progress_note}",
            worker_count=len(coverage.workers),
            covered_queues=covered,
            missing_queues=missing,
            busy=busy_healthy,
            error_code=coverage.error_code,
        )

    return QueueHealth(
        state="unavailable",
        label="Queue Unavailable",
        detail="No workers reported required queue coverage.",
        worker_count=0,
        covered_queues=covered,
        missing_queues=missing,
        busy=False,
        error_code=coverage.error_code,
    )


def classify_batch_warning(batch: Batch, *, now: datetime | None = None) -> BatchWarning | None:
    """Classify stale display state without reconciling or mutating the batch."""
    now = now or datetime.now(UTC)
    jobs = list(getattr(batch, "jobs", ()) or ())
    terminal_jobs = [job for job in jobs if job.status in {"completed", "failed", "cancelled"}]
    active_jobs = [job for job in jobs if job.status in ACTIVE_JOB_STATUSES]

    if jobs and len(terminal_jobs) == len(jobs):
        return BatchWarning(
            batch_id=str(batch.id),
            reason="terminal_jobs_unreconciled",
            detail="All child jobs are terminal, but the batch is still marked active.",
        )

    stale_jobs = [job for job in active_jobs if is_pipeline_job_stale(job, now=now)]
    if stale_jobs:
        return BatchWarning(
            batch_id=str(batch.id),
            reason="stale_active_jobs",
            detail=f"{len(stale_jobs)} active child job(s) have exceeded their stage timeout.",
        )

    created_at = getattr(batch, "created_at", None)
    if created_at is not None:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        else:
            created_at = created_at.astimezone(UTC)
        stale_after = timedelta(minutes=settings.pipeline_stale_timeout_queued_minutes)
        if batch.status == "running" and not active_jobs and now - created_at > stale_after:
            return BatchWarning(
                batch_id=str(batch.id),
                reason="running_without_active_jobs",
                detail="The batch is marked running but has no active child jobs.",
            )

    return None


async def load_channel_video_counts(db: AsyncSession) -> dict[object, int]:
    rows = (
        await db.execute(
            select(Channel.id, func.count(Video.id))
            .outerjoin(Video, Video.channel_id == Channel.id)
            .group_by(Channel.id)
        )
    ).all()
    return {channel_id: int(count or 0) for channel_id, count in rows}


async def build_operations_summary(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    queue_probe: Callable[[], QueueCoverage] | None = None,
) -> OperationsSummary:
    now = now or datetime.now(UTC)
    recent_cutoff = now - RECENT_COMPLETION_WINDOW

    counts = OperationsCounts(
        total_videos=int(await db.scalar(select(func.count(Video.id))) or 0),
        completed_videos=int(
            await db.scalar(select(func.count(Video.id)).where(Video.status == "completed")) or 0
        ),
        total_channels=int(await db.scalar(select(func.count(Channel.id))) or 0),
        active_jobs=int(
            await db.scalar(
                select(func.count(Job.id)).where(
                    Job.status == "running",
                    Job.hidden_from_queue.is_(False),
                )
            )
            or 0
        ),
        pending_jobs=int(
            await db.scalar(
                select(func.count(Job.id)).where(
                    Job.status.in_(PENDING_JOB_STATUSES),
                    Job.hidden_from_queue.is_(False),
                )
            )
            or 0
        ),
        failed_visible_jobs=int(
            await db.scalar(
                select(func.count(Job.id))
                .join(Video, Video.id == Job.video_id)
                .where(
                    Job.status == "failed",
                    Job.hidden_from_queue.is_(False),
                    Video.dismissed_at.is_(None),
                )
            )
            or 0
        ),
        recent_completions=int(
            await db.scalar(
                select(func.count(Job.id)).where(
                    Job.status == "completed",
                    Job.completed_at >= recent_cutoff,
                )
            )
            or 0
        ),
        report_delivery_warnings=int(
            await db.scalar(
                select(func.count(VideoReport.id)).where(
                    or_(
                        VideoReport.delivery_status == "failed",
                        VideoReport.delivery_error.is_not(None),
                    )
                )
            )
            or 0
        ),
        subscription_warnings=int(
            await db.scalar(
                select(func.count(ChannelSubscription.id)).where(
                    ChannelSubscription.enabled.is_(True),
                    ChannelSubscription.consecutive_failure_count > 0,
                )
            )
            or 0
        ),
    )

    batch_result = await db.execute(
        select(Batch)
        .options(selectinload(Batch.jobs))
        .where(Batch.status.in_(["pending", "running"]))
        .order_by(Batch.created_at)
    )
    active_batches = tuple(batch_result.scalars().all())
    batch_warnings = tuple(
        warning
        for batch in active_batches
        if (warning := classify_batch_warning(batch, now=now)) is not None
    )

    job_result = await db.execute(
        select(Job).where(
            Job.job_type == "pipeline",
            Job.status.in_(ACTIVE_JOB_STATUSES),
            Job.hidden_from_queue.is_(False),
        )
    )
    health_jobs = list(job_result.scalars().all())

    probe = queue_probe or inspect_queue_coverage
    coverage = await asyncio.to_thread(probe)
    return OperationsSummary(
        generated_at=now,
        counts=counts,
        queue_health=derive_queue_health(coverage, health_jobs),
        runtime=RuntimeCapabilities(
            transcription_engine=settings.transcription_engine,
            # The web process configuration does not prove which engine every
            # native worker loaded, so user-facing copy stays capability-based.
            transcription_label="Local transcription pipeline",
            inline_diarization_enabled=settings.inline_diarization_enabled,
            transcript_cleanup_enabled=settings.transcript_cleanup_enabled,
            report_delivery_enabled=(
                settings.report_generation_enabled and settings.report_delivery_enabled
            ),
        ),
        active_batches=active_batches,
        batch_warnings=batch_warnings,
    )


__all__ = [
    "ACTIVE_JOB_STATUSES",
    "BatchWarning",
    "OperationsCounts",
    "OperationsSummary",
    "QueueCoverage",
    "QueueHealth",
    "RuntimeCapabilities",
    "build_operations_summary",
    "classify_batch_warning",
    "derive_queue_health",
    "inspect_queue_coverage",
    "load_channel_video_counts",
]
