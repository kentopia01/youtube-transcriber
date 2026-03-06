import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.job import Job
from app.models.video import Video
from app.schemas.video import VideoSubmit
from app.services.youtube import extract_video_id, get_video_info, is_channel_url
from app.tasks.pipeline import run_pipeline

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.post("")
async def submit_video(
    request: Request,
    data: VideoSubmit,
    db: AsyncSession = Depends(get_db),
):
    """Submit a YouTube video URL for processing."""
    url = data.url.strip()

    # Check if it's a channel URL
    if is_channel_url(url):
        raise HTTPException(
            status_code=400,
            detail="This looks like a channel URL. Please use the channel submission form.",
        )

    # Extract video ID
    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Could not extract a valid YouTube video ID from URL.")

    # Check if already exists
    result = await db.execute(
        select(Video).where(Video.youtube_video_id == video_id)
    )
    existing = result.scalar_one_or_none()
    if existing:
        # If the video previously failed, allow re-processing
        if existing.status == "failed":
            existing.status = "pending"
            existing.error_message = None
        else:
            # Return existing video's job for non-failed videos
            job_result = await db.execute(
                select(Job).where(Job.video_id == existing.id).order_by(Job.created_at.desc())
            )
            job = job_result.scalars().first()
            if job:
                return {"job_id": str(job.id), "video_id": str(existing.id), "status": "existing"}
            # Re-process if no job exists
            existing.status = "pending"
            existing.error_message = None

    # Get video info
    try:
        info = get_video_info(f"https://www.youtube.com/watch?v={video_id}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch video info: {e}")

    if not existing:
        # Parse published date
        published_at = None
        if info.get("published_at"):
            try:
                published_at = datetime.strptime(info["published_at"], "%Y%m%d")
            except (ValueError, TypeError):
                pass

        video = Video(
            youtube_video_id=video_id,
            title=info.get("title", "Unknown"),
            description=info.get("description"),
            url=info.get("url", url),
            duration_seconds=info.get("duration"),
            published_at=published_at,
            thumbnail_url=info.get("thumbnail"),
            status="pending",
        )
        db.add(video)
        await db.flush()
    else:
        video = existing

    # Create job
    job = Job(
        video_id=video.id,
        job_type="pipeline",
        status="queued",
        progress_message="Queued for processing",
    )
    db.add(job)
    await db.commit()

    # Launch pipeline
    celery_id = run_pipeline(str(video.id))
    job.celery_task_id = celery_id
    await db.commit()

    return {"job_id": str(job.id), "video_id": str(video.id), "status": "queued"}
