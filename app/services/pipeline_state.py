from datetime import UTC, datetime
from typing import Any

from app.models.job import Job

PIPELINE_STAGE_QUEUED = "queued"
PIPELINE_STAGE_DOWNLOAD = "download"
PIPELINE_STAGE_TRANSCRIBE = "transcribe"
PIPELINE_STAGE_DIARIZE = "diarize"
PIPELINE_STAGE_CLEANUP = "cleanup"
PIPELINE_STAGE_SUMMARIZE = "summarize"
PIPELINE_STAGE_EMBED = "embed"
PIPELINE_STAGE_COMPLETED = "completed"
PIPELINE_STAGE_CANCELLED = "cancelled"

PIPELINE_STAGE_SEQUENCE = (
    PIPELINE_STAGE_DOWNLOAD,
    PIPELINE_STAGE_TRANSCRIBE,
    PIPELINE_STAGE_DIARIZE,
    PIPELINE_STAGE_CLEANUP,
    PIPELINE_STAGE_SUMMARIZE,
    PIPELINE_STAGE_EMBED,
)

PIPELINE_ATTEMPT_ACTIVE_STATUSES = ("pending", "queued", "running")
PIPELINE_ATTEMPT_TERMINAL_STATUSES = ("completed", "failed", "cancelled")
PIPELINE_TERMINAL_ONLY_STAGES = (PIPELINE_STAGE_COMPLETED, PIPELINE_STAGE_CANCELLED)

_SENTINEL = object()


def classify_pipeline_attempt(job: Job | Any) -> str | None:
    """Return the machine-safe attempt bucket for a pipeline job.

    - active: pending/queued/running
    - terminal: completed/failed/cancelled
    - superseded: hidden superseded failed attempts
    """
    if getattr(job, "job_type", None) != "pipeline":
        return None

    if (
        getattr(job, "hidden_reason", None) == "superseded"
        and getattr(job, "superseded_by_job_id", None) is not None
    ):
        return "superseded"

    status = getattr(job, "status", None)
    if status in PIPELINE_ATTEMPT_ACTIVE_STATUSES:
        return "active"

    if status in PIPELINE_ATTEMPT_TERMINAL_STATUSES:
        return "terminal"

    return "unknown"


def set_pipeline_job_state(
    job: Job,
    *,
    lifecycle_status: str | None = None,
    current_stage: str | None | object = _SENTINEL,
    progress_pct: float | object = _SENTINEL,
    progress_message: str | None | object = _SENTINEL,
    error_message: str | None | object = _SENTINEL,
    started_at: datetime | None | object = _SENTINEL,
    completed_at: datetime | None | object = _SENTINEL,
) -> None:
    """Apply a consistent lifecycle + stage transition for pipeline jobs."""
    now = datetime.now(UTC)
    resolved_stage = current_stage
    existing_stage = getattr(job, "current_stage", None)
    state_changed = False

    if lifecycle_status is not None:
        state_changed = state_changed or getattr(job, "status", None) != lifecycle_status
        job.status = lifecycle_status

        if lifecycle_status == "running" and started_at is _SENTINEL and job.started_at is None:
            job.started_at = now

        if lifecycle_status in PIPELINE_ATTEMPT_ACTIVE_STATUSES and completed_at is _SENTINEL:
            job.completed_at = None

        if lifecycle_status in PIPELINE_ATTEMPT_TERMINAL_STATUSES and completed_at is _SENTINEL:
            job.completed_at = now

        # Keep lifecycle and stage semantics aligned, without inferring stage
        # from progress percentage.
        if lifecycle_status in {"pending", "queued"}:
            resolved_stage = PIPELINE_STAGE_QUEUED
        elif lifecycle_status == "completed":
            resolved_stage = PIPELINE_STAGE_COMPLETED
        elif lifecycle_status == "cancelled":
            resolved_stage = PIPELINE_STAGE_CANCELLED
        elif lifecycle_status == "running":
            candidate_stage = (
                resolved_stage if resolved_stage is not _SENTINEL else existing_stage
            )
            if candidate_stage in PIPELINE_TERMINAL_ONLY_STAGES:
                resolved_stage = (
                    existing_stage
                    if existing_stage not in PIPELINE_TERMINAL_ONLY_STAGES
                    and existing_stage is not None
                    else PIPELINE_STAGE_QUEUED
                )

    if resolved_stage is not _SENTINEL:
        if existing_stage != resolved_stage:
            job.current_stage = resolved_stage
            job.stage_updated_at = now
            state_changed = True
        elif getattr(job, "stage_updated_at", None) is None:
            job.stage_updated_at = now
            state_changed = True

    if progress_pct is not _SENTINEL:
        state_changed = state_changed or getattr(job, "progress_pct", None) != float(progress_pct)
        job.progress_pct = float(progress_pct)

    if progress_message is not _SENTINEL:
        state_changed = state_changed or getattr(job, "progress_message", None) != progress_message
        job.progress_message = progress_message

    if error_message is not _SENTINEL:
        state_changed = state_changed or getattr(job, "error_message", None) != error_message
        job.error_message = error_message

    if started_at is not _SENTINEL:
        job.started_at = started_at

    if completed_at is not _SENTINEL:
        job.completed_at = completed_at

    if state_changed or getattr(job, "last_activity_at", None) is None:
        job.last_activity_at = now
