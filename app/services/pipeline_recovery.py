import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.job import Job
from app.models.video import Video
from app.services.pipeline_observability import get_task_worker_identity
from app.services.pipeline_state import set_pipeline_job_state

MANUAL_REVIEW_RECOVERY_STATUS = "manual_review"
STALE_REAP_RECOVERY_STATUS = "stale_reaped"

RETRY_LIMITS_BY_STAGE = {
    "download": 3,
    "transcribe": 0,
    "diarize": 0,
    "cleanup": 0,
    "summarize": 2,
    "embed": 2,
}


def get_stage_retry_limit(stage: str | None) -> int:
    return RETRY_LIMITS_BY_STAGE.get(stage or "", 0)


def get_stage_stale_timeout_minutes(stage: str | None) -> int:
    mapping = {
        "queued": settings.pipeline_stale_timeout_queued_minutes,
        "download": settings.pipeline_stale_timeout_download_minutes,
        "transcribe": settings.pipeline_stale_timeout_transcribe_minutes,
        "diarize": settings.pipeline_stale_timeout_diarize_minutes,
        "cleanup": settings.pipeline_stale_timeout_cleanup_minutes,
        "summarize": settings.pipeline_stale_timeout_summarize_minutes,
        "embed": settings.pipeline_stale_timeout_embed_minutes,
    }
    return mapping.get(stage or "queued", settings.pipeline_stale_timeout_transcribe_minutes)


def get_job_activity_anchor(job: Job) -> datetime | None:
    return (
        getattr(job, "last_activity_at", None)
        or getattr(job, "stage_updated_at", None)
        or getattr(job, "started_at", None)
        or getattr(job, "created_at", None)
    )


def is_pipeline_job_stale(job: Job, now: datetime | None = None) -> bool:
    if job.job_type != "pipeline" or job.status not in {"pending", "queued", "running"}:
        return False

    anchor = get_job_activity_anchor(job)
    if anchor is None:
        return False

    if now is None:
        now = datetime.now(UTC)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)

    timeout = timedelta(minutes=get_stage_stale_timeout_minutes(job.current_stage))
    return now - anchor > timeout


def normalize_failure_text(message: str) -> str:
    normalized = (message or "").strip().lower()
    normalized = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<uuid>", normalized)
    normalized = re.sub(r"https?://\S+", "<url>", normalized)
    normalized = re.sub(r"/[^\s]+", "<path>", normalized)
    normalized = re.sub(r"\b\d+\b", "#", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized[:180]


def build_failure_signature(stage: str | None, error: Exception | str) -> str:
    exc_type = error.__class__.__name__ if isinstance(error, Exception) else "Error"
    message = str(error)
    return f"{stage or 'unknown'}|{exc_type}|{normalize_failure_text(message)}"[:255]


def count_prior_identical_failures(db: Session, job: Job, signature: str) -> int:
    if not job.video_id:
        return 0

    return (
        db.query(func.count(Job.id))
        .filter(
            Job.video_id == job.video_id,
            Job.job_type == "pipeline",
            Job.status == "failed",
            Job.failure_signature == signature,
            Job.id != job.id,
        )
        .scalar()
        or 0
    )


def get_retry_block_reason(job: Job | None) -> str | None:
    if not job:
        return None
    if getattr(job, "recovery_status", None) == MANUAL_REVIEW_RECOVERY_STATUS:
        return job.recovery_reason or "Manual review required before another retry"
    return None


def record_pipeline_failure(
    db: Session,
    job: Job | None,
    *,
    video: Video | None,
    stage: str | None,
    error: Exception | str,
    default_message: str,
    stale_reap: bool = False,
    task=None,
) -> str:
    final_message = default_message

    if job:
        signature = build_failure_signature(stage, error)
        signature_count = count_prior_identical_failures(db, job, signature) + 1
        job.failure_signature = signature
        job.failure_signature_count = signature_count
        job.recovery_status = STALE_REAP_RECOVERY_STATUS if stale_reap else None
        job.recovery_reason = default_message if stale_reap else None

        if signature_count >= settings.pipeline_manual_review_after_failures:
            job.recovery_status = MANUAL_REVIEW_RECOVERY_STATUS
            job.recovery_reason = (
                f"Manual review required after {signature_count} identical failures "
                f"in stage '{stage or 'unknown'}'."
            )
            final_message = f"{default_message} Manual review required after {signature_count} identical failures."

        worker_hostname = worker_task_id = None
        if task is not None:
            worker_hostname, worker_task_id = get_task_worker_identity(task)

        set_pipeline_job_state(
            job,
            lifecycle_status="failed",
            current_stage=stage,
            error_message=str(error),
            progress_message=final_message,
            worker_hostname=worker_hostname,
            worker_task_id=worker_task_id,
        )

    if video:
        video.status = "failed"
        video.error_message = final_message

    return final_message
