"""Shared helpers for pipeline task files."""

import os
import uuid
from typing import Any

from celery.exceptions import Ignore
from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.transcription import Transcription
from app.models.video import Video
from app.services.pipeline_observability import get_task_worker_identity
from app.services.pipeline_state import (
    PIPELINE_ATTEMPT_ACTIVE_STATUSES,
    PIPELINE_STAGE_CLEANUP,
    PIPELINE_STAGE_DIARIZE,
    PIPELINE_STAGE_DOWNLOAD,
    PIPELINE_STAGE_EMBED,
    PIPELINE_STAGE_QUEUED,
    PIPELINE_STAGE_SUMMARIZE,
    PIPELINE_STAGE_TRANSCRIBE,
    set_pipeline_job_state,
)

_SENTINEL = object()

ALLOWED_STAGE_OWNERSHIP: dict[str, set[str]] = {
    PIPELINE_STAGE_DOWNLOAD: {
        PIPELINE_STAGE_QUEUED,
        PIPELINE_STAGE_DOWNLOAD,
    },
    PIPELINE_STAGE_TRANSCRIBE: {
        PIPELINE_STAGE_QUEUED,
        PIPELINE_STAGE_DOWNLOAD,
        PIPELINE_STAGE_TRANSCRIBE,
    },
    PIPELINE_STAGE_DIARIZE: {
        PIPELINE_STAGE_QUEUED,
        PIPELINE_STAGE_TRANSCRIBE,
        PIPELINE_STAGE_DIARIZE,
    },
    PIPELINE_STAGE_CLEANUP: {
        PIPELINE_STAGE_QUEUED,
        PIPELINE_STAGE_TRANSCRIBE,
        PIPELINE_STAGE_DIARIZE,
        PIPELINE_STAGE_CLEANUP,
    },
    PIPELINE_STAGE_SUMMARIZE: {
        PIPELINE_STAGE_QUEUED,
        PIPELINE_STAGE_TRANSCRIBE,
        PIPELINE_STAGE_DIARIZE,
        PIPELINE_STAGE_CLEANUP,
        PIPELINE_STAGE_SUMMARIZE,
    },
    PIPELINE_STAGE_EMBED: {
        PIPELINE_STAGE_QUEUED,
        PIPELINE_STAGE_SUMMARIZE,
        PIPELINE_STAGE_EMBED,
    },
}


def build_pipeline_task_payload(video_id: uuid.UUID | str, job_id: uuid.UUID | str) -> dict[str, str]:
    return {"video_id": str(video_id), "job_id": str(job_id)}


def parse_pipeline_task_payload(payload: dict[str, str] | str) -> tuple[uuid.UUID, uuid.UUID | None]:
    if isinstance(payload, str):
        return uuid.UUID(payload), None

    return uuid.UUID(payload["video_id"]), uuid.UUID(payload["job_id"]) if payload.get("job_id") else None


def get_latest_pipeline_job(db: Session, video_id: uuid.UUID) -> Job | None:
    return (
        db.query(Job)
        .filter(Job.video_id == video_id, Job.job_type == "pipeline")
        .order_by(Job.created_at.desc())
        .first()
    )


def get_pipeline_job_context(
    db: Session,
    payload: dict[str, str] | str,
    *,
    expected_stage: str,
    require_audio: bool = False,
    require_transcription: bool = False,
) -> tuple[dict[str, str], Video, Job]:
    video_id, job_id = parse_pipeline_task_payload(payload)
    normalized_payload = build_pipeline_task_payload(video_id, job_id or "") if job_id else {"video_id": str(video_id)}

    video = db.get(Video, video_id)
    if video is None:
        raise Ignore()

    if job_id is None:
        job = get_latest_pipeline_job(db, video_id)
    else:
        job = db.get(Job, job_id)

    if job is None or job.job_type != "pipeline" or job.video_id != video_id:
        raise Ignore()

    active_attempt = (
        db.query(Job)
        .filter(
            Job.video_id == video_id,
            Job.job_type == "pipeline",
            Job.status.in_(PIPELINE_ATTEMPT_ACTIVE_STATUSES),
        )
        .order_by(Job.created_at.desc())
        .first()
    )
    if active_attempt is not None and active_attempt.id != job.id:
        raise Ignore()

    if job.status not in PIPELINE_ATTEMPT_ACTIVE_STATUSES:
        raise Ignore()

    if getattr(job, "hidden_reason", None) == "superseded" or getattr(job, "superseded_by_job_id", None):
        raise Ignore()

    current_stage = getattr(job, "current_stage", None) or PIPELINE_STAGE_QUEUED
    allowed_stages = ALLOWED_STAGE_OWNERSHIP.get(expected_stage)
    if allowed_stages is None or current_stage not in allowed_stages:
        raise Ignore()

    if require_audio:
        audio_path = (video.audio_file_path or "").strip()
        if not audio_path or not os.path.exists(audio_path):
            raise Ignore()

    if require_transcription:
        has_transcription = (
            db.query(Transcription.id)
            .filter(Transcription.video_id == video_id)
            .first()
            is not None
        )
        if not has_transcription:
            raise Ignore()

    normalized_payload["job_id"] = str(job.id)
    return normalized_payload, video, job


def update_pipeline_job(
    job: Job | None,
    *,
    lifecycle_status: str | None = None,
    current_stage: str | None | object = _SENTINEL,
    progress_pct: float | object = _SENTINEL,
    progress_message: str | None | object = _SENTINEL,
    error_message: str | None | object = _SENTINEL,
    started_at=_SENTINEL,
    completed_at=_SENTINEL,
    task: Any | None = None,
) -> None:
    if not job:
        return

    kwargs = {}
    if lifecycle_status is not None:
        kwargs["lifecycle_status"] = lifecycle_status
    if current_stage is not _SENTINEL:
        kwargs["current_stage"] = current_stage
    if progress_pct is not _SENTINEL:
        kwargs["progress_pct"] = progress_pct
    if progress_message is not _SENTINEL:
        kwargs["progress_message"] = progress_message
    if error_message is not _SENTINEL:
        kwargs["error_message"] = error_message
    if started_at is not _SENTINEL:
        kwargs["started_at"] = started_at
    if completed_at is not _SENTINEL:
        kwargs["completed_at"] = completed_at
    if task is not None:
        worker_hostname, worker_task_id = get_task_worker_identity(task)
        kwargs["worker_hostname"] = worker_hostname
        kwargs["worker_task_id"] = worker_task_id

    set_pipeline_job_state(job, **kwargs)
