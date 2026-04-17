import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db
from app.models.embedding_chunk import EmbeddingChunk
from app.models.job import Job
from app.models.summary import Summary
from app.models.transcription import Transcription
from app.models.video import Video
from app.schemas.video import JobResponse
from app.services.job_visibility import hide_superseded_failed_jobs
from app.services.pipeline_state import (
    PIPELINE_STAGE_CANCELLED,
    PIPELINE_STAGE_QUEUED,
    set_pipeline_job_state,
)
from app.services.pipeline_attempts import (
    get_active_pipeline_attempt,
    get_latest_pipeline_attempt,
    is_active_pipeline_attempt_conflict,
)
from app.services.pipeline_observability import (
    ATTEMPT_REASON_STALE_RECOVERY,
    ATTEMPT_REASON_USER_RETRY,
    build_artifact_check_result,
)
from app.services.pipeline_recovery import STALE_REAP_RECOVERY_STATUS, get_retry_block_reason
from app.tasks.pipeline import run_pipeline_from

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}")
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse.model_validate(job)


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in ("pending", "queued"):
        set_pipeline_job_state(
            job,
            lifecycle_status="cancelled",
            current_stage=PIPELINE_STAGE_CANCELLED,
            progress_message="Cancelled by user",
        )
        if job.video_id:
            video_result = await db.execute(select(Video).where(Video.id == job.video_id))
            video = video_result.scalar_one_or_none()
            if video:
                video.status = "pending"
                video.error_message = None
        await db.commit()
        return {"status": "cancelled"}

    raise HTTPException(status_code=400, detail="Can only cancel pending or queued jobs")


@router.post("/{job_id}/retry")
async def retry_job(job_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "failed":
        raise HTTPException(status_code=400, detail="Can only retry failed jobs")

    if job.job_type != "pipeline" or not job.video_id:
        raise HTTPException(status_code=400, detail="Only failed pipeline jobs can be retried")

    retry_block_reason = get_retry_block_reason(job)
    if retry_block_reason:
        raise HTTPException(status_code=409, detail=retry_block_reason)

    video_result = await db.execute(select(Video).where(Video.id == job.video_id))
    video = video_result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    video.status = "pending"
    video.error_message = None

    # One-active-attempt guard.
    existing_attempt = await get_active_pipeline_attempt(db, video.id)
    if existing_attempt:
        return {
            "status": existing_attempt.status,
            "job_id": str(existing_attempt.id),
            "video_id": str(video.id),
        }

    latest_attempt = await get_latest_pipeline_attempt(db, job.video_id)
    retry_block_reason = get_retry_block_reason(latest_attempt or job)
    if retry_block_reason:
        raise HTTPException(status_code=409, detail=retry_block_reason)

    # Artifact-aware retry planning.
    start_from, artifact_check_result = await _detect_resume_point(db, video)

    video_uuid = video.id
    attempt_number = ((latest_attempt.attempt_number if latest_attempt else 0) or 0) + 1
    start_label = start_from.split(".")[-1]

    attempt_reason = (
        ATTEMPT_REASON_STALE_RECOVERY
        if job.recovery_status == STALE_REAP_RECOVERY_STATUS
        else ATTEMPT_REASON_USER_RETRY
    )

    retry = Job(
        video_id=video_uuid,
        channel_id=job.channel_id,
        job_type="pipeline",
        status="queued",
        attempt_number=attempt_number,
        supersedes_job_id=job.id,
        attempt_creation_reason=attempt_reason,
        last_artifact_check_result=artifact_check_result,
    )
    set_pipeline_job_state(
        retry,
        lifecycle_status="queued",
        current_stage=PIPELINE_STAGE_QUEUED,
        progress_pct=0.0,
        progress_message=f"Queued retry attempt #{attempt_number} (resuming from {start_label})",
        error_message=None,
        started_at=None,
        completed_at=None,
    )
    db.add(retry)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if not is_active_pipeline_attempt_conflict(exc):
            raise

        active_attempt = await get_active_pipeline_attempt(db, video_uuid)
        if not active_attempt:
            raise HTTPException(status_code=409, detail="Active pipeline attempt already exists")

        return {
            "status": active_attempt.status,
            "job_id": str(active_attempt.id),
            "video_id": str(video_uuid),
        }

    await hide_superseded_failed_jobs(
        db,
        video_id=video_uuid,
        superseded_by_job_id=retry.id,
    )

    retry.celery_task_id = run_pipeline_from(
        str(video_uuid),
        start_from=start_from,
        job_id=str(retry.id),
    )
    await db.commit()

    payload = {"status": "queued", "job_id": str(retry.id), "video_id": str(video_uuid)}
    if request.headers.get("HX-Request"):
        response = JSONResponse(payload)
        response.headers["HX-Redirect"] = f"/jobs/{retry.id}"
        return response

    return payload


async def _detect_resume_point(db: AsyncSession, video: Video) -> tuple[str, dict]:
    """Choose the safest pipeline stage to resume from based on available artifacts."""
    video_id = video.id

    emb_result = await db.execute(
        select(EmbeddingChunk.id).where(EmbeddingChunk.video_id == video_id).limit(1)
    )
    has_embeddings = emb_result.scalar_one_or_none() is not None

    sum_result = await db.execute(select(Summary.id).where(Summary.video_id == video_id).limit(1))
    has_summary = sum_result.scalar_one_or_none() is not None

    tx_result = await db.execute(
        select(Transcription.id).where(Transcription.video_id == video_id).limit(1)
    )
    has_transcription = tx_result.scalar_one_or_none() is not None

    audio_path = (video.audio_file_path or "").strip()
    has_audio = bool(audio_path and os.path.exists(audio_path))

    diarization_requires_audio = settings.diarization_enabled and bool(settings.hf_token)
    selected_stage = _select_resume_stage(
        has_embeddings=has_embeddings,
        has_summary=has_summary,
        has_transcription=has_transcription,
        has_audio=has_audio,
        diarization_requires_audio=diarization_requires_audio,
    )
    artifact_check_result = build_artifact_check_result(
        has_embeddings=has_embeddings,
        has_summary=has_summary,
        has_transcription=has_transcription,
        has_audio=has_audio,
        diarization_requires_audio=diarization_requires_audio,
        selected_resume_stage=selected_stage,
    )

    return selected_stage, artifact_check_result


def _select_resume_stage(
    *,
    has_embeddings: bool,
    has_summary: bool,
    has_transcription: bool,
    has_audio: bool,
    diarization_requires_audio: bool,
) -> str:
    """Pick a resume stage only when that stage's required artifacts exist."""
    if has_embeddings and has_transcription:
        return "tasks.generate_embeddings"

    if has_summary and has_transcription:
        return "tasks.generate_embeddings"

    if has_transcription:
        if diarization_requires_audio:
            if has_audio:
                return "tasks.diarize_and_align"
            return "tasks.download_audio"
        return "tasks.cleanup_transcript"

    if has_audio:
        return "tasks.transcribe_audio"

    return "tasks.download_audio"
