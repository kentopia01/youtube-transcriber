import math
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.batch import Batch
from app.models.channel import Channel
from app.models.job import Job
from app.models.video import Video
from app.schemas.video import ChannelSubmit, ChannelVideoSelection, ChatToggle
from app.services.youtube import discover_channel_videos, is_channel_url
from app.tasks.pipeline import run_pipeline

router = APIRouter(prefix="/api/channels", tags=["channels"])

BATCH_SIZE = 50


@router.post("")
async def submit_channel(
    request: Request,
    data: ChannelSubmit,
    db: AsyncSession = Depends(get_db),
):
    """Submit a YouTube channel URL for video discovery."""
    url = data.url.strip()

    if not is_channel_url(url):
        raise HTTPException(status_code=400, detail="This doesn't look like a YouTube channel URL.")

    # Discover channel videos
    try:
        result = discover_channel_videos(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch channel info: {e}")

    channel_yt_id = result.get("channel_id", "")
    if not channel_yt_id:
        raise HTTPException(status_code=400, detail="Could not determine channel ID.")

    # Get or create channel
    existing = await db.execute(
        select(Channel).where(Channel.youtube_channel_id == channel_yt_id)
    )
    channel = existing.scalar_one_or_none()

    if not channel:
        channel = Channel(
            youtube_channel_id=channel_yt_id,
            name=result.get("channel_name", "Unknown"),
            url=url,
            description=result.get("description"),
            thumbnail_url=result.get("thumbnail"),
            video_count=len(result.get("videos", [])),
        )
        db.add(channel)
        await db.flush()
    else:
        channel.name = result.get("channel_name", channel.name)
        channel.video_count = len(result.get("videos", []))

    await db.commit()

    return {
        "channel_id": str(channel.id),
        "channel_name": channel.name,
        "videos": result.get("videos", []),
    }


@router.post("/{channel_id}/process")
async def process_selected_videos(
    channel_id: uuid.UUID,
    data: ChannelVideoSelection,
    db: AsyncSession = Depends(get_db),
):
    """Queue selected channel videos for processing in batches."""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    video_ids = data.video_ids
    if not video_ids:
        raise HTTPException(status_code=400, detail="No videos selected")

    total_batches = math.ceil(len(video_ids) / BATCH_SIZE)
    created_jobs = []

    for batch_num in range(total_batches):
        batch_video_ids = video_ids[batch_num * BATCH_SIZE : (batch_num + 1) * BATCH_SIZE]

        batch = Batch(
            channel_id=channel.id,
            batch_number=batch_num + 1,
            total_batches=total_batches,
            total_videos=len(batch_video_ids),
            status="pending" if batch_num > 0 else "running",
        )
        db.add(batch)
        await db.flush()

        for yt_video_id in batch_video_ids:
            # Get or create video record
            v_result = await db.execute(
                select(Video).where(Video.youtube_video_id == yt_video_id)
            )
            video = v_result.scalar_one_or_none()

            if not video:
                video = Video(
                    youtube_video_id=yt_video_id,
                    channel_id=channel.id,
                    title="Pending...",
                    url=f"https://www.youtube.com/watch?v={yt_video_id}",
                    status="pending",
                )
                db.add(video)
                await db.flush()

            job = Job(
                video_id=video.id,
                channel_id=channel.id,
                batch_id=batch.id,
                job_type="pipeline",
                status="queued" if batch_num == 0 else "pending",
                progress_message="Queued for processing" if batch_num == 0 else f"Waiting for batch {batch_num}",
            )
            db.add(job)
            await db.flush()

            # Only launch first batch immediately
            if batch_num == 0:
                celery_id = run_pipeline(str(video.id))
                job.celery_task_id = celery_id

            created_jobs.append(str(job.id))

    await db.commit()

    return {
        "channel_id": str(channel.id),
        "total_videos": len(video_ids),
        "total_batches": total_batches,
        "jobs_created": len(created_jobs),
    }


@router.patch("/{channel_id}/chat-toggle")
async def toggle_channel_chat(
    channel_id: uuid.UUID,
    data: ChatToggle,
    db: AsyncSession = Depends(get_db),
):
    """Toggle chat_enabled for a channel and all its videos."""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    channel.chat_enabled = data.enabled

    # Bulk-update all videos belonging to this channel
    video_result = await db.execute(
        select(Video).where(Video.channel_id == channel_id)
    )
    videos = video_result.scalars().all()
    for video in videos:
        video.chat_enabled = data.enabled

    await db.commit()
    return {
        "channel_id": str(channel.id),
        "chat_enabled": channel.chat_enabled,
        "videos_updated": len(videos),
    }
