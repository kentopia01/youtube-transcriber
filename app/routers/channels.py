import math
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.batch import Batch
from app.models.channel import Channel
from app.models.job import Job
from app.models.video import Video
from app.schemas.video import ChannelSubmit, ChannelVideoSelection, ChatToggle
from app.services.channel_sync import (
    get_or_create_channel,
    refresh_channel_video_count,
    sync_discovered_videos,
)
from app.services.channel_dispatcher import dispatch_channel_backlog
from app.services.job_visibility import hide_superseded_failed_jobs
from app.services.pipeline_attempts import (
    ATTEMPT_RESULT_ALREADY_ACTIVE,
    ATTEMPT_RESULT_BLOCKED,
    ATTEMPT_RESULT_CREATED,
    PipelineAttemptAllocation,
    allocate_pipeline_attempt_async,
    create_pipeline_attempt_from_allocation_async,
)
from app.services.pipeline_enqueue import PipelineEnqueueError
from app.services.pipeline_observability import ATTEMPT_REASON_CHANNEL_PROCESS
from app.services.pipeline_state import PIPELINE_STAGE_QUEUED, set_pipeline_job_state
from app.services.youtube import discover_channel_videos, is_channel_url

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
        result = discover_channel_videos(
            url,
            limit=data.limit,
            after_date=data.after_date,
            before_date=data.before_date,
            min_duration=data.min_duration,
            max_duration=data.max_duration,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch channel info: {e}")

    channel_yt_id = result.get("channel_id", "")
    if not channel_yt_id:
        raise HTTPException(status_code=400, detail="Could not determine channel ID.")

    channel = await get_or_create_channel(
        db,
        youtube_channel_id=channel_yt_id,
        name=result.get("channel_name", "Unknown"),
        url=url,
        description=result.get("description"),
        thumbnail_url=result.get("thumbnail"),
        last_synced_at=datetime.now(UTC),
    )
    if not channel:
        raise HTTPException(status_code=400, detail="Could not create channel record.")

    await sync_discovered_videos(db, channel, result.get("videos", []))
    await refresh_channel_video_count(db, channel)

    await db.commit()

    try:
        from app.services.telegram_notify import notify as _tg_notify

        _tg_notify(
            "channel.queued",
            {
                "channel_id": str(channel.id),
                "channel_name": channel.name,
                "video_count": len(result.get("videos", [])),
            },
        )
    except Exception:  # noqa: BLE001
        pass

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
    if not video_ids and data.latest:
        # Auto-select the N most recent videos for this channel
        latest_result = await db.execute(
            select(Video.youtube_video_id)
            .where(Video.channel_id == channel_id)
            .order_by(Video.created_at.desc())
            .limit(data.latest)
        )
        video_ids = [row[0] for row in latest_result.all()]
    if not video_ids:
        raise HTTPException(status_code=400, detail="No videos selected")

    video_results: list[dict[str, object]] = []
    eligible: list[tuple[str, Video, PipelineAttemptAllocation, dict[str, object]]] = []
    seen_youtube_ids: set[str] = set()

    for yt_video_id in video_ids:
        result_entry: dict[str, object] = {"youtube_video_id": yt_video_id}
        video_results.append(result_entry)

        if yt_video_id in seen_youtube_ids:
            result_entry.update(
                {
                    "status": "skipped",
                    "reason": "duplicate_selected",
                }
            )
            continue
        seen_youtube_ids.add(yt_video_id)

        v_result = await db.execute(select(Video).where(Video.youtube_video_id == yt_video_id))
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
        else:
            video.channel_id = channel.id

        allocation = await allocate_pipeline_attempt_async(db, video.id)
        if allocation.status == ATTEMPT_RESULT_ALREADY_ACTIVE:
            result_entry.update(
                {
                    "video_id": str(video.id),
                    "status": "already_active",
                    "active_job_id": str(allocation.active_job.id) if allocation.active_job else None,
                    "reason": allocation.reason or "active_attempt_exists",
                }
            )
            continue

        if allocation.status == ATTEMPT_RESULT_BLOCKED:
            result_entry.update(
                {
                    "video_id": str(video.id),
                    "status": "blocked",
                    "reason": allocation.reason or "Pipeline attempt is blocked",
                }
            )
            continue

        if not allocation.ready:
            result_entry.update(
                {
                    "video_id": str(video.id),
                    "status": "error",
                    "reason": allocation.reason or "attempt_allocation_failed",
                }
            )
            continue

        eligible.append((yt_video_id, video, allocation, result_entry))

    created_jobs: list[str] = []
    created_attempts: list[Job] = []

    for _yt_video_id, video, allocation, result_entry in eligible:
        if video.status in {"discovered", "failed", "cancelled"}:
            video.status = "pending"
            video.error_message = None

        attempt = await create_pipeline_attempt_from_allocation_async(
            db,
            allocation,
            status="pending",
            current_stage=PIPELINE_STAGE_QUEUED,
            progress_message="Waiting for channel dispatcher",
            channel_id=channel.id,
            batch_id=None,
            attempt_creation_reason=ATTEMPT_REASON_CHANNEL_PROCESS,
        )

        if attempt.status == ATTEMPT_RESULT_CREATED and attempt.job is not None:
            created_jobs.append(str(attempt.job.id))
            created_attempts.append(attempt.job)
            await hide_superseded_failed_jobs(
                db,
                video_id=video.id,
                superseded_by_job_id=attempt.job.id,
            )
            result_entry.update(
                {
                    "video_id": str(video.id),
                    "status": "created",
                    "job_id": str(attempt.job.id),
                    "attempt_number": attempt.attempt_number,
                }
            )
            continue

        if attempt.status == ATTEMPT_RESULT_ALREADY_ACTIVE:
            result_entry.update(
                {
                    "video_id": str(video.id),
                    "status": "already_active",
                    "active_job_id": str(attempt.active_job.id) if attempt.active_job else None,
                    "reason": attempt.reason or "active_attempt_exists",
                }
            )
            continue

        if attempt.status == ATTEMPT_RESULT_BLOCKED:
            result_entry.update(
                {
                    "video_id": str(video.id),
                    "status": "blocked",
                    "reason": attempt.reason or "Pipeline attempt is blocked",
                }
            )
            continue

        result_entry.update(
            {
                "video_id": str(video.id),
                "status": "error",
                "reason": attempt.reason or "attempt_create_error",
            }
        )

    total_batches = math.ceil(len(created_attempts) / BATCH_SIZE) if created_attempts else 0
    for batch_num in range(total_batches):
        batch_jobs = created_attempts[batch_num * BATCH_SIZE : (batch_num + 1) * BATCH_SIZE]
        batch = Batch(
            channel_id=channel.id,
            batch_number=batch_num + 1,
            total_batches=total_batches,
            total_videos=len(batch_jobs),
            status="pending" if batch_num > 0 else "running",
        )
        db.add(batch)
        await db.flush()

        progress_message = (
            "Waiting for channel dispatcher"
            if batch_num == 0
            else f"Waiting for batch {batch_num + 1}"
        )
        for job in batch_jobs:
            job.batch_id = batch.id
            set_pipeline_job_state(
                job,
                lifecycle_status="pending",
                current_stage=PIPELINE_STAGE_QUEUED,
                progress_message=progress_message,
            )

    await db.commit()
    dispatched_job_ids: list[str] = []
    if created_jobs:
        try:
            dispatched_job_ids = await db.run_sync(
                lambda sync_db: dispatch_channel_backlog(sync_db, max_jobs=1)
            )
        except PipelineEnqueueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "channel_id": str(channel.id),
        "total_videos": len(video_ids),
        "total_batches": total_batches,
        "jobs_created": len(created_jobs),
        "dispatched_job_ids": dispatched_job_ids,
        "video_results": video_results,
    }


@router.get("/{channel_id}/persona")
async def get_channel_persona(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return the channel's persona (if generated) and readiness status."""
    from app.services.persona import (
        SCOPE_CHANNEL,
        channel_needs_persona,
        count_completed_videos,
        get_persona,
    )

    channel = await db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")

    completed = await count_completed_videos(db, channel_id)
    persona = await get_persona(db, SCOPE_CHANNEL, str(channel_id))
    should_generate, reason = await channel_needs_persona(db, channel_id)

    from app.config import settings as _s

    return {
        "channel_id": str(channel.id),
        "channel_name": channel.name,
        "completed_videos": completed,
        "min_videos": _s.persona_min_videos,
        "persona": (
            None
            if persona is None
            else {
                "id": str(persona.id),
                "display_name": persona.display_name,
                "persona_prompt": persona.persona_prompt,
                "style_notes": persona.style_notes,
                "confidence": persona.confidence,
                "source_chunk_count": persona.source_chunk_count,
                "videos_at_generation": persona.videos_at_generation,
                "generated_at": persona.generated_at.isoformat() if persona.generated_at else None,
                "generated_by_model": persona.generated_by_model,
                "is_stale": should_generate and persona is not None,
            }
        ),
        "ready": persona is not None,
        "should_generate": should_generate,
        "reason": reason,
    }


@router.post("/{channel_id}/generate-persona")
async def trigger_channel_persona(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger (or re-trigger) channel persona generation.

    Enqueues the Celery task on the `post` queue. Non-blocking — check status
    via ``GET /api/channels/{id}/persona``.
    """
    from app.services.persona import count_completed_videos
    from app.tasks.generate_persona import enqueue_channel_persona

    channel = await db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")

    from app.config import settings as _s

    completed = await count_completed_videos(db, channel_id)
    if completed < _s.persona_min_videos:
        raise HTTPException(
            status_code=400,
            detail=f"Channel has {completed}/{_s.persona_min_videos} completed videos; persona generation needs at least {_s.persona_min_videos}.",
        )

    enqueue_channel_persona(str(channel_id), forced=True)
    return {
        "channel_id": str(channel.id),
        "status": "enqueued",
        "completed_videos": completed,
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
