"""Safe auto-retry sweep for transient cleanup/summarize provider failures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import uuid

from sqlalchemy.orm import Session

from app.config import settings
from app.models.job import Job
from app.models.video import Video
from app.services.job_visibility import hide_superseded_failed_jobs_sync
from app.services.pipeline_attempts import (
    ATTEMPT_RESULT_ALREADY_ACTIVE,
    ATTEMPT_RESULT_BLOCKED,
    ATTEMPT_RESULT_CREATED,
    allocate_pipeline_attempt_sync,
    create_pipeline_attempt_from_allocation_sync,
)
from app.services.pipeline_enqueue import enqueue_pipeline_job_after_commit
from app.services.pipeline_observability import ATTEMPT_REASON_TRANSIENT_AUTO_RETRY
from app.services.pipeline_recovery import (
    MANUAL_REVIEW_RECOVERY_STATUS,
    get_retry_block_reason,
)
from app.services.pipeline_resume import detect_resume_point_sync
from app.services.pipeline_state import PIPELINE_STAGE_QUEUED
from app.services.provider_retry import RETRYABLE_PROVIDER_EXCEPTION_NAMES
from app.tasks.pipeline import run_pipeline_from

TRANSIENT_AUTO_RETRY_STAGES = {"cleanup", "summarize"}
TRANSIENT_SIGNATURE_MARKERS = (
    "connection error",
    "connection reset",
    "timed out",
    "timeout",
    "rate limit",
    "too many requests",
    "temporarily unavailable",
    "server error",
    "internal server error",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
)
DEFAULT_MAX_AGE_HOURS = 24.0
DEFAULT_LIMIT = 25


@dataclass(slots=True)
class TransientRetryDecision:
    job_id: str
    video_id: str | None
    status: str
    reason: str
    start_from: str | None = None
    new_job_id: str | None = None
    active_job_id: str | None = None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _failure_time(job: Job) -> datetime | None:
    return _as_utc(
        getattr(job, "completed_at", None)
        or getattr(job, "last_activity_at", None)
        or getattr(job, "created_at", None)
    )


def failure_signature_is_known_transient(signature: str | None) -> bool:
    """Match known transient cleanup/summarize provider signatures."""
    if not signature:
        return False

    stage, sep, remainder = signature.partition("|")
    if not sep or stage not in TRANSIENT_AUTO_RETRY_STAGES:
        return False

    exc_name, sep, normalized_message = remainder.partition("|")
    if exc_name in RETRYABLE_PROVIDER_EXCEPTION_NAMES:
        return True

    normalized_message = normalized_message.lower() if sep else remainder.lower()
    return any(marker in normalized_message for marker in TRANSIENT_SIGNATURE_MARKERS)


def evaluate_transient_retry_candidate(
    job: Job,
    *,
    latest_attempt: Job | None,
    active_attempt: Job | None,
    now: datetime | None = None,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> TransientRetryDecision:
    """Apply auto-retry guardrails for a single failed pipeline job."""
    now = now or datetime.now(UTC)
    job_id = str(getattr(job, "id", ""))
    video_id = str(job.video_id) if getattr(job, "video_id", None) else None

    def skipped(reason: str, *, active_job_id: str | None = None) -> TransientRetryDecision:
        return TransientRetryDecision(
            job_id=job_id,
            video_id=video_id,
            status="skipped",
            reason=reason,
            active_job_id=active_job_id,
        )

    if job.job_type != "pipeline" or job.status != "failed":
        return skipped("not_failed_pipeline_job")

    if not job.video_id:
        return skipped("missing_video_id")

    if getattr(job, "hidden_from_queue", False) or getattr(job, "hidden_reason", None) == "superseded":
        return skipped("superseded_or_hidden_failure")

    retry_block_reason = get_retry_block_reason(job)
    if retry_block_reason or getattr(job, "recovery_status", None) == MANUAL_REVIEW_RECOVERY_STATUS:
        return skipped("manual_review")

    if not failure_signature_is_known_transient(getattr(job, "failure_signature", None)):
        return skipped("not_known_transient_failure")

    signature_count = getattr(job, "failure_signature_count", 0) or 0
    if signature_count >= settings.pipeline_manual_review_after_failures:
        return skipped("retry_limit_reached")

    failed_at = _failure_time(job)
    if failed_at is not None and now - failed_at > timedelta(hours=max_age_hours):
        return skipped("too_old")

    if active_attempt is not None:
        return skipped("active_attempt_exists", active_job_id=str(active_attempt.id))

    if latest_attempt is not None and latest_attempt.id != job.id:
        latest_block_reason = get_retry_block_reason(latest_attempt)
        if latest_block_reason:
            return skipped("latest_attempt_manual_review")
        return skipped("not_latest_attempt")

    return TransientRetryDecision(
        job_id=job_id,
        video_id=video_id,
        status="eligible",
        reason="known_transient_failure",
    )


def find_transient_failure_candidates(
    db: Session,
    *,
    limit: int = DEFAULT_LIMIT,
) -> list[Job]:
    """Load recent failed pipeline attempts for in-Python transient filtering."""
    return (
        db.query(Job)
        .filter(
            Job.job_type == "pipeline",
            Job.status == "failed",
            Job.hidden_from_queue.is_(False),
        )
        .order_by(Job.completed_at.desc(), Job.created_at.desc())
        .limit(limit)
        .all()
    )


def retry_transient_failures(
    db: Session,
    *,
    dry_run: bool = True,
    limit: int = DEFAULT_LIMIT,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> list[TransientRetryDecision]:
    """Plan or enqueue retries for recent transient cleanup/summarize failures.

    The sweep reuses artifact-aware resume planning, honors manual-review and
    one-active-attempt guardrails, and only enqueues at most one retry per video.
    """
    now = datetime.now(UTC)
    decisions: list[TransientRetryDecision] = []
    enqueued_video_ids: set[uuid.UUID] = set()
    for job in find_transient_failure_candidates(db, limit=limit):
        if job.video_id in enqueued_video_ids:
            decisions.append(
                TransientRetryDecision(
                    job_id=str(job.id),
                    video_id=str(job.video_id) if job.video_id else None,
                    status="skipped",
                    reason="active_attempt_exists",
                )
            )
            continue

        allocation = (
            allocate_pipeline_attempt_sync(db, job.video_id)
            if job.video_id
            else None
        )
        if allocation is not None and allocation.status == ATTEMPT_RESULT_ALREADY_ACTIVE:
            decisions.append(
                TransientRetryDecision(
                    job_id=str(job.id),
                    video_id=str(job.video_id) if job.video_id else None,
                    status="skipped",
                    reason="active_attempt_exists",
                    active_job_id=str(allocation.active_job.id) if allocation.active_job else None,
                )
            )
            continue
        if allocation is not None and allocation.status == ATTEMPT_RESULT_BLOCKED:
            decisions.append(
                TransientRetryDecision(
                    job_id=str(job.id),
                    video_id=str(job.video_id) if job.video_id else None,
                    status="skipped",
                    reason=(
                        "manual_review"
                        if allocation.latest_job is not None and allocation.latest_job.id == job.id
                        else "latest_attempt_manual_review"
                    ),
                )
            )
            continue

        decision = evaluate_transient_retry_candidate(
            job,
            latest_attempt=allocation.latest_job if allocation is not None else None,
            active_attempt=None,
            now=now,
            max_age_hours=max_age_hours,
        )
        if decision.status != "eligible":
            decisions.append(decision)
            continue

        if dry_run:
            decisions.append(
                TransientRetryDecision(
                    job_id=decision.job_id,
                    video_id=decision.video_id,
                    status="planned",
                    reason="dry_run_known_transient_failure",
                )
            )
            continue

        video = db.get(Video, job.video_id)
        if video is None:
            decisions.append(
                TransientRetryDecision(
                    job_id=decision.job_id,
                    video_id=decision.video_id,
                    status="skipped",
                    reason="missing_video",
                )
            )
            continue

        if allocation is None:
            decisions.append(
                TransientRetryDecision(
                    job_id=decision.job_id,
                    video_id=decision.video_id,
                    status="skipped",
                    reason="missing_video_id",
                )
            )
            continue

        start_from, artifact_check_result = detect_resume_point_sync(db, video)
        start_label = start_from.split(".")[-1]

        video.status = "pending"
        video.error_message = None
        if hasattr(video, "dismissed_at"):
            video.dismissed_at = None
        if hasattr(video, "dismissed_reason"):
            video.dismissed_reason = None

        attempt = create_pipeline_attempt_from_allocation_sync(
            db,
            allocation,
            status="queued",
            current_stage=PIPELINE_STAGE_QUEUED,
            progress_message=lambda attempt_number: (
                f"Queued transient auto-retry attempt #{attempt_number} "
                f"(resuming from {start_label})"
            ),
            channel_id=job.channel_id,
            supersedes_job_id=job.id,
            attempt_creation_reason=ATTEMPT_REASON_TRANSIENT_AUTO_RETRY,
            last_artifact_check_result=artifact_check_result,
        )
        if attempt.status == ATTEMPT_RESULT_ALREADY_ACTIVE:
            decisions.append(
                TransientRetryDecision(
                    job_id=decision.job_id,
                    video_id=decision.video_id,
                    status="skipped",
                    reason="active_attempt_exists",
                    active_job_id=str(attempt.active_job.id) if attempt.active_job else None,
                )
            )
            continue
        if attempt.status == ATTEMPT_RESULT_BLOCKED:
            decisions.append(
                TransientRetryDecision(
                    job_id=decision.job_id,
                    video_id=decision.video_id,
                    status="skipped",
                    reason=(
                        "manual_review"
                        if attempt.latest_job is not None and attempt.latest_job.id == job.id
                        else "latest_attempt_manual_review"
                    ),
                )
            )
            continue
        if attempt.status != ATTEMPT_RESULT_CREATED or attempt.job is None:
            decisions.append(
                TransientRetryDecision(
                    job_id=decision.job_id,
                    video_id=decision.video_id,
                    status="skipped",
                    reason=attempt.reason or "attempt_create_error",
                )
            )
            continue

        retry_job = attempt.job
        hide_superseded_failed_jobs_sync(
            db,
            video_id=job.video_id,
            superseded_by_job_id=retry_job.id,
        )
        video_id_str = str(job.video_id)
        retry_job_id_str = str(retry_job.id)
        enqueue_pipeline_job_after_commit(
            db,
            retry_job,
            publish=lambda: run_pipeline_from(
                video_id_str,
                start_from=start_from,
                job_id=retry_job_id_str,
            ),
        )
        enqueued_video_ids.add(job.video_id)
        decisions.append(
            TransientRetryDecision(
                job_id=decision.job_id,
                video_id=decision.video_id,
                status="queued",
                reason="known_transient_failure",
                start_from=start_from,
                new_job_id=str(retry_job.id),
            )
        )

    return decisions
