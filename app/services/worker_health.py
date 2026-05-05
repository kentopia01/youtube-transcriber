from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable

from app.models.job import Job
from app.services.pipeline_recovery import is_pipeline_job_stale

# Heavy stages can be healthy for a long time if they are not stale.
LONG_RUNNING_STAGES = {"transcribe", "diarize"}
# Post stages need a fresher DB/log signal so health checks do not mask a dead
# post worker for the full stale timeout.
POST_BUSY_STAGES = {"cleanup", "summarize", "embed"}
POST_PROGRESS_WINDOW_MINUTES = 15
POST_LOG_PROGRESS_MARKERS = (
    "tasks.cleanup_transcript",
    "tasks.summarize_transcription",
    "tasks.generate_embeddings",
    "cleaning_chunk",
    "chunked_cleanup",
    "transcript_cleanup_complete",
    "summarizing",
    "chunked_summarization",
    "summary generated",
    "succeeded",
)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _activity_anchor(job: Job) -> datetime | None:
    return _as_utc(
        getattr(job, "last_activity_at", None)
        or getattr(job, "stage_updated_at", None)
        or getattr(job, "current_stage_started_at", None)
        or getattr(job, "started_at", None)
        or getattr(job, "created_at", None)
    )


def recent_post_log_progress_at(
    log_path: str | Path | None,
    *,
    now: datetime | None = None,
    within_minutes: int = POST_PROGRESS_WINDOW_MINUTES,
) -> datetime | None:
    """Return log mtime when the post-worker log shows recent progress."""
    if not log_path:
        return None

    path = Path(log_path)
    try:
        stat = path.stat()
    except OSError:
        return None

    mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    now = now or datetime.now(UTC)
    if now - mtime > timedelta(minutes=within_minutes):
        return None

    try:
        tail = path.read_text(errors="ignore")[-12000:].lower()
    except OSError:
        return None

    if any(marker in tail for marker in POST_LOG_PROGRESS_MARKERS):
        return mtime
    return None


def _recent_enough(value: datetime | None, now: datetime, minutes: int) -> bool:
    value = _as_utc(value)
    if value is None:
        return False
    return now - value <= timedelta(minutes=minutes)


def job_is_busy_but_healthy(
    job: Job,
    now: datetime | None = None,
    *,
    post_log_progress_at: datetime | None = None,
    post_progress_window_minutes: int = POST_PROGRESS_WINDOW_MINUTES,
) -> bool:
    if job.job_type != "pipeline" or job.status not in {"pending", "queued", "running"}:
        return False

    if now is None:
        now = datetime.now(UTC)

    if is_pipeline_job_stale(job, now=now):
        return False

    if job.current_stage in LONG_RUNNING_STAGES:
        return _activity_anchor(job) is not None

    if job.current_stage in POST_BUSY_STAGES:
        return _recent_enough(
            _activity_anchor(job),
            now,
            post_progress_window_minutes,
        ) or _recent_enough(post_log_progress_at, now, post_progress_window_minutes)

    return False


def any_busy_healthy_jobs(
    jobs: Iterable[Job],
    now: datetime | None = None,
    *,
    post_log_path: str | Path | None = None,
    post_log_progress_at: datetime | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    if post_log_progress_at is None and post_log_path is not None:
        post_log_progress_at = recent_post_log_progress_at(post_log_path, now=now)

    return any(
        job_is_busy_but_healthy(
            job,
            now=now,
            post_log_progress_at=post_log_progress_at,
        )
        for job in jobs
    )
