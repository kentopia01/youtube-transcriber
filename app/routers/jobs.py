import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.job import Job
from app.models.video import Video
from app.schemas.video import JobResponse
from app.schemas.inventory import JobInventoryItem, JobInventoryPage
from app.services.job_visibility import hide_superseded_failed_jobs
from app.services.pipeline_state import (
    PIPELINE_STAGE_CANCELLED,
    PIPELINE_STAGE_QUEUED,
    set_pipeline_job_state,
)
from app.services.pipeline_attempts import (
    ATTEMPT_RESULT_ALREADY_ACTIVE,
    ATTEMPT_RESULT_BLOCKED,
    ATTEMPT_RESULT_CREATED,
    allocate_pipeline_attempt_async,
    create_pipeline_attempt_from_allocation_async,
)
from app.services.pipeline_observability import (
    ATTEMPT_REASON_STALE_RECOVERY,
    ATTEMPT_REASON_USER_RETRY,
)
from app.services.pipeline_enqueue import PipelineEnqueueError, enqueue_pipeline_job_after_commit_async
from app.services.pipeline_recovery import STALE_REAP_RECOVERY_STATUS, get_retry_block_reason
from app.services.pipeline_resume import detect_resume_point_async, select_resume_stage
from app.tasks.pipeline import run_pipeline_from

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=JobInventoryPage)
async def list_jobs(
    status: str | None = None,
    stage: str | None = None,
    channel_id: uuid.UUID | None = None,
    video_id: uuid.UUID | None = None,
    include_hidden: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    filters = []
    if status:
        filters.append(Job.status == status)
    if stage:
        filters.append(Job.current_stage == stage)
    if channel_id:
        filters.append(Job.channel_id == channel_id)
    if video_id:
        filters.append(Job.video_id == video_id)
    if not include_hidden:
        filters.append(Job.hidden_from_queue.is_(False))

    total = int(await db.scalar(select(func.count(Job.id)).where(*filters)) or 0)
    rows = (
        await db.execute(
            select(Job, Video)
            .outerjoin(Video, Video.id == Job.video_id)
            .where(*filters)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = [
        JobInventoryItem(
            id=job.id,
            video_id=job.video_id,
            video_title=video.title if video else None,
            youtube_video_id=video.youtube_video_id if video else None,
            channel_id=job.channel_id,
            job_type=job.job_type,
            status=job.status,
            current_stage=job.current_stage,
            progress_pct=job.progress_pct,
            attempt_number=job.attempt_number,
            attempt_creation_reason=job.attempt_creation_reason,
            error_message=job.error_message,
            hidden_from_queue=job.hidden_from_queue,
            created_at=job.created_at,
            completed_at=job.completed_at,
        )
        for job, video in rows
    ]
    return JobInventoryPage(items=items, total=total, limit=limit, offset=offset)


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
    # Retrying a dismissed video = user actually cares about it again.
    video.dismissed_at = None
    video.dismissed_reason = None

    video_uuid = video.id
    allocation = await allocate_pipeline_attempt_async(db, video_uuid)
    if allocation.status == ATTEMPT_RESULT_ALREADY_ACTIVE and allocation.active_job is not None:
        return {
            "status": allocation.active_job.status,
            "job_id": str(allocation.active_job.id),
            "video_id": str(video_uuid),
        }

    if allocation.status == ATTEMPT_RESULT_BLOCKED:
        raise HTTPException(status_code=409, detail=allocation.reason or "Pipeline attempt is blocked")

    # Artifact-aware retry planning.
    start_from, artifact_check_result = await _detect_resume_point(db, video)

    start_label = start_from.split(".")[-1]

    attempt_reason = (
        ATTEMPT_REASON_STALE_RECOVERY
        if job.recovery_status == STALE_REAP_RECOVERY_STATUS
        else ATTEMPT_REASON_USER_RETRY
    )

    attempt = await create_pipeline_attempt_from_allocation_async(
        db,
        allocation,
        status="queued",
        current_stage=PIPELINE_STAGE_QUEUED,
        progress_message=lambda attempt_number: (
            f"Queued retry attempt #{attempt_number} (resuming from {start_label})"
        ),
        channel_id=job.channel_id,
        supersedes_job_id=job.id,
        attempt_creation_reason=attempt_reason,
        last_artifact_check_result=artifact_check_result,
    )
    if attempt.status == ATTEMPT_RESULT_ALREADY_ACTIVE and attempt.active_job is not None:
        return {
            "status": attempt.active_job.status,
            "job_id": str(attempt.active_job.id),
            "video_id": str(video_uuid),
        }
    if attempt.status == ATTEMPT_RESULT_BLOCKED:
        raise HTTPException(status_code=409, detail=attempt.reason or "Pipeline attempt is blocked")
    if attempt.status != ATTEMPT_RESULT_CREATED or attempt.job is None:
        raise HTTPException(status_code=409, detail=attempt.reason or "Could not create pipeline attempt")

    retry = attempt.job
    await hide_superseded_failed_jobs(
        db,
        video_id=video_uuid,
        superseded_by_job_id=retry.id,
    )

    video_id_str = str(video_uuid)
    retry_job_id_str = str(retry.id)
    try:
        await enqueue_pipeline_job_after_commit_async(
            db,
            retry,
            publish=lambda: run_pipeline_from(
                video_id_str,
                start_from=start_from,
                job_id=retry_job_id_str,
            ),
        )
    except PipelineEnqueueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    payload = {"status": "queued", "job_id": retry_job_id_str, "video_id": video_id_str}
    if request.headers.get("HX-Request"):
        response = JSONResponse(payload)
        response.headers["HX-Redirect"] = f"/jobs/{retry.id}"
        return response

    return payload


async def _detect_resume_point(db: AsyncSession, video: Video) -> tuple[str, dict]:
    """Choose the safest pipeline stage to resume from based on available artifacts."""
    return await detect_resume_point_async(db, video)


def _select_resume_stage(
    *,
    has_embeddings: bool,
    has_summary: bool,
    has_transcription: bool,
    has_audio: bool,
    diarization_requires_audio: bool,
) -> str:
    """Backward-compatible wrapper for tests/imports around shared resume logic."""
    return select_resume_stage(
        has_embeddings=has_embeddings,
        has_summary=has_summary,
        has_transcription=has_transcription,
        has_audio=has_audio,
        diarization_requires_audio=diarization_requires_audio,
    )
