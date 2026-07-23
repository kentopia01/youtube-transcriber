import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.job import Job
from app.models.video import Video
from app.schemas.video import ChatToggle, VideoResponse, VideoSubmit
from app.schemas.inventory import VideoInventoryItem, VideoInventoryPage
from app.models.channel import Channel
from app.models.reader_state import READER_STATUSES, ReaderState
from app.models.transcription import Transcription
from app.services.channel_sync import get_or_create_channel, parse_upload_date
from app.services.job_visibility import hide_superseded_failed_jobs
from app.services.pipeline_state import PIPELINE_STAGE_QUEUED
from app.services.pipeline_attempts import (
    ATTEMPT_RESULT_ALREADY_ACTIVE,
    ATTEMPT_RESULT_BLOCKED,
    ATTEMPT_RESULT_CREATED,
    create_pipeline_attempt_async,
)
from app.services.pipeline_observability import (
    ATTEMPT_REASON_MANUAL_RESUBMIT,
    ATTEMPT_REASON_VIDEO_SUBMIT,
)
from app.services.pipeline_enqueue import PipelineEnqueueError, enqueue_pipeline_job_after_commit_async
from app.services.youtube import extract_video_id, get_video_info, is_channel_url
from app.tasks.pipeline import run_pipeline

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.get("", response_model=VideoInventoryPage)
async def list_videos(
    status: str | None = None,
    channel_id: uuid.UUID | None = None,
    reader_status: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    include_dismissed: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    if reader_status and reader_status not in READER_STATUSES:
        raise HTTPException(status_code=422, detail="Unknown reader status")
    filters = []
    if status:
        filters.append(Video.status == status)
    if channel_id:
        filters.append(Video.channel_id == channel_id)
    if not include_dismissed:
        filters.append(Video.dismissed_at.is_(None))
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        filters.append(or_(Video.title.ilike(pattern), Video.youtube_video_id.ilike(pattern)))
    if reader_status:
        filters.append(
            ReaderState.status == reader_status
            if reader_status != "unread"
            else or_(ReaderState.status == "unread", ReaderState.id.is_(None))
        )

    joins = (
        select(Video.id)
        .outerjoin(ReaderState, (ReaderState.video_id == Video.id) & ReaderState.digest_lane_id.is_(None))
        .where(*filters)
    )
    total = int(await db.scalar(select(func.count()).select_from(joins.subquery())) or 0)
    rows = (
        await db.execute(
            select(Video, Channel, ReaderState, Transcription.id)
            .outerjoin(Channel, Channel.id == Video.channel_id)
            .outerjoin(ReaderState, (ReaderState.video_id == Video.id) & ReaderState.digest_lane_id.is_(None))
            .outerjoin(Transcription, Transcription.video_id == Video.id)
            .where(*filters)
            .order_by(Video.created_at.desc(), Video.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = [
        VideoInventoryItem(
            id=video.id,
            youtube_video_id=video.youtube_video_id,
            channel_id=video.channel_id,
            channel_name=channel.name if channel else None,
            title=video.title,
            status=video.status,
            duration_seconds=video.duration_seconds,
            published_at=video.published_at,
            thumbnail_url=video.thumbnail_url,
            has_transcript=transcription_id is not None,
            reader_status=state.status if state else "unread",
            reader_progress_pct=state.progress_pct if state else 0.0,
            dismissed_at=video.dismissed_at,
            created_at=video.created_at,
        )
        for video, channel, state, transcription_id in rows
    ]
    return VideoInventoryPage(items=items, total=total, limit=limit, offset=offset)


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
    # Get video info
    try:
        info = get_video_info(f"https://www.youtube.com/watch?v={video_id}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch video info: {e}")

    channel = await get_or_create_channel(
        db,
        youtube_channel_id=info.get("channel_id"),
        name=info.get("channel_name"),
        url=info.get("channel_url"),
    )

    published_at = parse_upload_date(info.get("published_at"))

    existing_was_failed = bool(existing and existing.status == "failed")

    if existing:
        existing.channel_id = channel.id if channel else existing.channel_id
        existing.title = info.get("title", existing.title)
        existing.description = info.get("description", existing.description)
        existing.url = info.get("url", existing.url)
        existing.duration_seconds = info.get("duration", existing.duration_seconds)
        existing.published_at = published_at or existing.published_at
        existing.thumbnail_url = info.get("thumbnail", existing.thumbnail_url)

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
                await db.commit()
                return {"job_id": str(job.id), "video_id": str(existing.id), "status": "existing"}
            # Re-process if no job exists
            existing.status = "pending"
            existing.error_message = None

    if not existing:
        video = Video(
            youtube_video_id=video_id,
            channel_id=channel.id if channel else None,
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

    video_uuid = video.id
    attempt = await create_pipeline_attempt_async(
        db,
        video_id=video_uuid,
        status="queued",
        current_stage=PIPELINE_STAGE_QUEUED,
        progress_message=lambda attempt_number: f"Queued for processing (attempt #{attempt_number})",
        attempt_creation_reason=(
            ATTEMPT_REASON_MANUAL_RESUBMIT if existing_was_failed else ATTEMPT_REASON_VIDEO_SUBMIT
        ),
    )

    if attempt.status == ATTEMPT_RESULT_ALREADY_ACTIVE and attempt.active_job is not None:
        await db.commit()
        return {
            "job_id": str(attempt.active_job.id),
            "video_id": str(video_uuid),
            "status": "existing",
        }

    if attempt.status == ATTEMPT_RESULT_BLOCKED:
        raise HTTPException(status_code=409, detail=attempt.reason or "Pipeline attempt is blocked")

    if attempt.status != ATTEMPT_RESULT_CREATED or attempt.job is None:
        raise HTTPException(status_code=409, detail=attempt.reason or "Could not create pipeline attempt")

    job = attempt.job
    if existing_was_failed:
        await hide_superseded_failed_jobs(
            db,
            video_id=video_uuid,
            superseded_by_job_id=job.id,
        )

    video_id_str = str(video_uuid)
    job_id_str = str(job.id)
    try:
        await enqueue_pipeline_job_after_commit_async(
            db,
            job,
            publish=lambda: run_pipeline(video_id_str, job_id=job_id_str),
        )
    except PipelineEnqueueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"job_id": job_id_str, "video_id": video_id_str, "status": "queued"}


@router.get("/{video_id}", response_model=VideoResponse)
async def get_video(video_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get video metadata by internal UUID. Used by Siftly integration to poll status."""
    result = await db.execute(select(Video).where(Video.id == video_id))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


@router.post("/{video_id}/dismiss")
async def dismiss_video(
    video_id: uuid.UUID,
    data: dict | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Hide this video from queue/failed ops views. Reversible via undismiss
    or via a retry (which auto-un-dismisses)."""
    result = await db.execute(select(Video).where(Video.id == video_id))
    video = result.scalar_one_or_none()
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    from datetime import UTC, datetime as _dt

    video.dismissed_at = _dt.now(UTC)
    if data and data.get("reason"):
        video.dismissed_reason = str(data["reason"])[:500]
    await db.commit()
    return {
        "video_id": str(video.id),
        "dismissed_at": video.dismissed_at.isoformat(),
        "dismissed_reason": video.dismissed_reason,
    }


@router.post("/{video_id}/undismiss")
async def undismiss_video(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Clear the dismiss marker so the video reappears in ops views."""
    result = await db.execute(select(Video).where(Video.id == video_id))
    video = result.scalar_one_or_none()
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    video.dismissed_at = None
    video.dismissed_reason = None
    await db.commit()
    return {"video_id": str(video.id), "dismissed_at": None}


@router.patch("/{video_id}/chat-toggle")
async def toggle_video_chat(
    video_id: uuid.UUID,
    data: ChatToggle,
    db: AsyncSession = Depends(get_db),
):
    """Toggle chat_enabled for a single video."""
    result = await db.execute(select(Video).where(Video.id == video_id))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    video.chat_enabled = data.enabled
    await db.commit()
    return {"video_id": str(video.id), "chat_enabled": video.chat_enabled}
