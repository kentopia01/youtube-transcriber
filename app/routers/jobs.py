import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.embedding_chunk import EmbeddingChunk
from app.models.job import Job
from app.models.summary import Summary
from app.models.transcription import Transcription
from app.models.video import Video
from app.schemas.video import JobResponse
from app.tasks.pipeline import run_pipeline, run_pipeline_from

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
        job.status = "cancelled"
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

    video_result = await db.execute(select(Video).where(Video.id == job.video_id))
    video = video_result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    video.status = "pending"
    video.error_message = None

    # Smart retry: detect where to resume based on existing data
    start_from = await _detect_resume_point(db, video.id)

    retry = Job(
        video_id=video.id,
        channel_id=job.channel_id,
        job_type="pipeline",
        status="queued",
        progress_pct=0.0,
        progress_message=f"Queued for retry (resuming from {start_from.split('.')[-1]})",
        error_message=None,
    )
    db.add(retry)
    await db.flush()

    retry.celery_task_id = run_pipeline_from(str(video.id), start_from=start_from)
    await db.commit()

    payload = {"status": "queued", "job_id": str(retry.id), "video_id": str(video.id)}
    if request.headers.get("HX-Request"):
        response = JSONResponse(payload)
        response.headers["HX-Redirect"] = f"/jobs/{retry.id}"
        return response

    return payload


async def _detect_resume_point(db: AsyncSession, video_id: uuid.UUID) -> str:
    """Detect the correct pipeline step to resume from based on existing data.

    Checks what artifacts already exist and returns the earliest step that
    still needs to run.
    """
    # Check for existing embeddings
    emb_result = await db.execute(
        select(EmbeddingChunk.id).where(EmbeddingChunk.video_id == video_id).limit(1)
    )
    has_embeddings = emb_result.scalar_one_or_none() is not None

    # Check for existing summary
    sum_result = await db.execute(
        select(Summary.id).where(Summary.video_id == video_id)
    )
    has_summary = sum_result.scalar_one_or_none() is not None

    # Check for existing transcription
    tx_result = await db.execute(
        select(Transcription.id).where(Transcription.video_id == video_id)
    )
    has_transcription = tx_result.scalar_one_or_none() is not None

    if has_embeddings:
        # Everything exists — just re-run embeddings to mark complete
        return "tasks.generate_embeddings"
    if has_summary:
        return "tasks.generate_embeddings"
    if has_transcription:
        # Transcription exists, skip download + transcribe, resume from diarize
        return "tasks.diarize_and_align"

    return "tasks.download_audio"
