import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_db
from app.models.batch import Batch
from app.models.channel import Channel
from app.models.chat_session import ChatSession
from app.models.job import Job
from app.models.transcription import Transcription
from app.models.transcription_segment import TranscriptionSegment
from app.models.video import Video

router = APIRouter()


@router.get("/")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    # Recent jobs
    result = await db.execute(
        select(Job).options(selectinload(Job.video)).order_by(Job.created_at.desc()).limit(10)
    )
    jobs = result.scalars().all()

    # Active/pending jobs for queue widget
    active_result = await db.execute(
        select(Job).options(selectinload(Job.video)).where(Job.status.in_(["running", "queued", "pending"])).order_by(Job.created_at.desc()).limit(5)
    )
    active_jobs = active_result.scalars().all()

    # Video counts
    total_videos = await db.scalar(select(func.count(Video.id)))
    completed_videos = await db.scalar(
        select(func.count(Video.id)).where(Video.status == "completed")
    )

    # Channel count
    total_channels = await db.scalar(select(func.count(Channel.id)))

    # Queue data
    pending_result = await db.execute(
        select(Job).options(selectinload(Job.video)).where(Job.status.in_(["pending", "queued"])).order_by(Job.created_at).limit(20)
    )
    pending_jobs = pending_result.scalars().all()

    completed_result = await db.execute(
        select(Job).options(selectinload(Job.video)).where(Job.status == "completed").order_by(Job.completed_at.desc()).limit(10)
    )
    completed_jobs = completed_result.scalars().all()

    failed_result = await db.execute(
        select(Job)
        .options(selectinload(Job.video))
        .join(Video, Video.id == Job.video_id)
        .where(
            Job.status == "failed",
            Job.hidden_from_queue.is_(False),
            Video.dismissed_at.is_(None),
        )
        .order_by(Job.completed_at.desc())
        .limit(10)
    )
    failed_jobs = failed_result.scalars().all()

    batch_result = await db.execute(
        select(Batch).where(Batch.status.in_(["pending", "running"])).order_by(Batch.created_at)
    )
    active_batches = batch_result.scalars().all()

    return request.app.state.templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "jobs": jobs,
            "active_jobs": active_jobs,
            "total_videos": total_videos or 0,
            "completed_videos": completed_videos or 0,
            "total_channels": total_channels or 0,
            "pending_jobs": pending_jobs,
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
            "active_batches": active_batches,
        },
    )


@router.get("/partials/recent-jobs")
async def recent_jobs_partial(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Job).options(selectinload(Job.video)).order_by(Job.created_at.desc()).limit(10)
    )
    jobs = result.scalars().all()
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/recent_jobs.html", {"request": request, "jobs": jobs}
    )


@router.get("/submit")
async def submit_page(request: Request):
    """Legacy route — redirects to dashboard."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/", status_code=302)


@router.get("/library")
async def library_page(
    request: Request,
    tab: str = "videos",
    page: int = 1,
    db: AsyncSession = Depends(get_db),
):
    per_page = 20
    offset = (page - 1) * per_page

    # Videos
    video_count = await db.scalar(select(func.count(Video.id))) or 0
    video_query = select(Video).order_by(Video.created_at.desc())
    video_result = await db.execute(video_query.offset(offset).limit(per_page))
    videos = video_result.scalars().all()
    total_video_pages = (video_count + per_page - 1) // per_page

    # Channels
    channel_result = await db.execute(select(Channel).order_by(Channel.name))
    channels = channel_result.scalars().all()

    return request.app.state.templates.TemplateResponse(
        request,
        "library.html",
        {
            "request": request,
            "tab": tab,
            "videos": videos,
            "channels": channels,
            "video_count": video_count,
            "page": page,
            "total_pages": total_video_pages,
        },
    )


@router.get("/videos")
async def video_list(
    request: Request,
    page: int = 1,
    channel_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    per_page = 20
    offset = (page - 1) * per_page

    query = select(Video).order_by(Video.created_at.desc())
    count_query = select(func.count(Video.id))

    if channel_id:
        cid = uuid.UUID(channel_id)
        query = query.where(Video.channel_id == cid)
        count_query = count_query.where(Video.channel_id == cid)

    total = await db.scalar(count_query) or 0
    result = await db.execute(query.offset(offset).limit(per_page))
    videos = result.scalars().all()

    total_pages = (total + per_page - 1) // per_page

    # For HTMX pagination requests, return partial
    if request.headers.get("HX-Request"):
        return request.app.state.templates.TemplateResponse(
            request,
            "partials/video_list.html",
            {
                "request": request,
                "videos": videos,
                "page": page,
                "total_pages": total_pages,
                "channel_id": channel_id,
            },
        )

    return request.app.state.templates.TemplateResponse(
        request,
        "videos.html",
        {
            "request": request,
            "videos": videos,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "channel_id": channel_id,
        },
    )


@router.get("/videos/{video_id}")
async def video_detail(request: Request, video_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Video).where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        return request.app.state.templates.TemplateResponse(
            request,
            "error.html", {"request": request, "message": "Video not found"}, status_code=404
        )

    # Get transcription with segments
    trans_result = await db.execute(
        select(Transcription)
        .options(selectinload(Transcription.segments))
        .where(Transcription.video_id == video_id)
    )
    transcription = trans_result.scalar_one_or_none()

    # Get summary
    from app.models.summary import Summary

    summary_result = await db.execute(
        select(Summary).where(Summary.video_id == video_id)
    )
    summary = summary_result.scalar_one_or_none()

    latest_job_result = await db.execute(
        select(Job).where(Job.video_id == video_id).order_by(Job.created_at.desc()).limit(1)
    )
    latest_job = latest_job_result.scalar_one_or_none()

    return request.app.state.templates.TemplateResponse(
        request,
        "video_detail.html",
        {
            "request": request,
            "video": video,
            "transcription": transcription,
            "summary": summary,
            "latest_job": latest_job,
        },
    )


@router.get("/channels")
async def channel_list(request: Request, db: AsyncSession = Depends(get_db)):
    """Legacy route — redirects to library channels tab."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/library?tab=channels", status_code=302)


@router.get("/channels/{channel_id}")
async def channel_detail(
    request: Request, channel_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    from app.config import settings as _s
    from app.services.persona import (
        SCOPE_CHANNEL,
        count_completed_videos,
        get_persona,
    )

    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        return request.app.state.templates.TemplateResponse(
            request,
            "error.html", {"request": request, "message": "Channel not found"}, status_code=404
        )

    videos_result = await db.execute(
        select(Video)
        .where(Video.channel_id == channel_id)
        .order_by(Video.published_at.desc().nullslast())
    )
    videos = videos_result.scalars().all()

    persona = await get_persona(db, SCOPE_CHANNEL, str(channel_id))
    completed_videos = await count_completed_videos(db, channel_id)

    return request.app.state.templates.TemplateResponse(
        request,
        "channel_detail.html",
        {
            "request": request,
            "channel": channel,
            "videos": videos,
            "persona": persona,
            "completed_videos": completed_videos,
            "persona_min_videos": _s.persona_min_videos,
        },
    )


@router.get("/channels/{channel_id}/chat")
async def channel_chat_page(
    request: Request, channel_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    from app.services.persona import SCOPE_CHANNEL, get_persona

    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        return request.app.state.templates.TemplateResponse(
            request,
            "error.html", {"request": request, "message": "Channel not found"}, status_code=404
        )

    persona = await get_persona(db, SCOPE_CHANNEL, str(channel_id))
    if persona is None:
        return request.app.state.templates.TemplateResponse(
            request,
            "error.html",
            {
                "request": request,
                "message": f"{channel.name} does not have a persona yet. Wait for ingestion to complete or trigger generation from the channel page.",
            },
            status_code=409,
        )

    return request.app.state.templates.TemplateResponse(
        request,
        "channel_chat.html",
        {"request": request, "channel": channel, "persona": persona},
    )


def _group_sessions_by_date(sessions):
    """Group chat sessions into (label, sessions_list) tuples for sidebar."""
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)

    groups = {}
    order = ["Today", "Yesterday", "This Week", "Older"]
    for s in sessions:
        dt = s.updated_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt >= today:
            label = "Today"
        elif dt >= yesterday:
            label = "Yesterday"
        elif dt >= week_ago:
            label = "This Week"
        else:
            label = "Older"
        groups.setdefault(label, []).append(s)
    return [(label, groups[label]) for label in order if label in groups]


@router.get("/chat")
async def chat_page(request: Request, db: AsyncSession = Depends(get_db)):
    # Get all sessions for sidebar
    sessions_result = await db.execute(
        select(ChatSession)
        .where(ChatSession.platform == "web")
        .order_by(ChatSession.updated_at.desc())
        .limit(50)
    )
    sessions = sessions_result.scalars().all()

    # Load most recent session if exists
    session = None
    if sessions:
        from sqlalchemy.orm import selectinload as _sil
        s_result = await db.execute(
            select(ChatSession)
            .where(ChatSession.id == sessions[0].id)
            .options(_sil(ChatSession.messages))
        )
        session = s_result.scalar_one_or_none()

    # Count active videos
    active_video_count = await db.scalar(
        select(func.count(Video.id)).where(Video.chat_enabled == True)
    ) or 0

    return request.app.state.templates.TemplateResponse(
        request,
        "chat.html",
        {
            "request": request,
            "sessions": sessions,
            "session_groups": _group_sessions_by_date(sessions),
            "session": session,
            "current_session_id": session.id if session else None,
            "active_video_count": active_video_count,
        },
    )


@router.get("/chat/{session_id}")
async def chat_session_page(
    request: Request,
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import selectinload as _sil

    # Load the requested session with messages
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(_sil(ChatSession.messages))
    )
    session = result.scalar_one_or_none()
    if not session:
        return request.app.state.templates.TemplateResponse(
            request,
            "error.html", {"request": request, "message": "Chat session not found"}, status_code=404
        )

    # Get all sessions for sidebar
    sessions_result = await db.execute(
        select(ChatSession)
        .where(ChatSession.platform == "web")
        .order_by(ChatSession.updated_at.desc())
        .limit(50)
    )
    sessions = sessions_result.scalars().all()

    # Count active videos
    active_video_count = await db.scalar(
        select(func.count(Video.id)).where(Video.chat_enabled == True)
    ) or 0

    return request.app.state.templates.TemplateResponse(
        request,
        "chat.html",
        {
            "request": request,
            "sessions": sessions,
            "session_groups": _group_sessions_by_date(sessions),
            "session": session,
            "current_session_id": session.id,
            "active_video_count": active_video_count,
        },
    )


@router.get("/search")
async def search_page(request: Request):
    return request.app.state.templates.TemplateResponse(
        request,
        "search.html", {"request": request}
    )


@router.get("/jobs/{job_id}")
async def job_detail(request: Request, job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).options(selectinload(Job.video)).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        return request.app.state.templates.TemplateResponse(
            request,
            "error.html", {"request": request, "message": "Job not found"}, status_code=404
        )

    video = job.video

    # For HTMX polling, return partial
    if request.headers.get("HX-Request"):
        return request.app.state.templates.TemplateResponse(
            request,
            "partials/job_status.html",
            {"request": request, "job": job, "video": video},
        )

    return request.app.state.templates.TemplateResponse(
        request,
        "job_detail.html", {"request": request, "job": job, "video": video}
    )


@router.get("/queue")
async def queue_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Queue data endpoint — serves both full page and HTMX partials."""
    # Active jobs
    active_result = await db.execute(
        select(Job).options(selectinload(Job.video)).where(Job.status == "running").order_by(Job.started_at.desc())
    )
    active_jobs = active_result.scalars().all()

    # Pending jobs
    pending_result = await db.execute(
        select(Job).options(selectinload(Job.video)).where(Job.status.in_(["pending", "queued"])).order_by(Job.created_at)
    )
    pending_jobs = pending_result.scalars().all()

    # Recent completed
    completed_result = await db.execute(
        select(Job).options(selectinload(Job.video)).where(Job.status == "completed").order_by(Job.completed_at.desc()).limit(20)
    )
    completed_jobs = completed_result.scalars().all()

    # Failed
    failed_result = await db.execute(
        select(Job)
        .options(selectinload(Job.video))
        .join(Video, Video.id == Job.video_id)
        .where(
            Job.status == "failed",
            Job.hidden_from_queue.is_(False),
            Video.dismissed_at.is_(None),
        )
        .order_by(Job.completed_at.desc())
        .limit(20)
    )
    failed_jobs = failed_result.scalars().all()

    # Active batches
    batch_result = await db.execute(
        select(Batch).where(Batch.status.in_(["pending", "running"])).order_by(Batch.created_at)
    )
    active_batches = batch_result.scalars().all()

    # For HTMX polling
    if request.headers.get("HX-Request"):
        return request.app.state.templates.TemplateResponse(
            request,
            "partials/queue_content.html",
            {
                "request": request,
                "active_jobs": active_jobs,
                "pending_jobs": pending_jobs,
                "completed_jobs": completed_jobs,
                "failed_jobs": failed_jobs,
                "active_batches": active_batches,
            },
        )

    return request.app.state.templates.TemplateResponse(
        request,
        "queue.html",
        {
            "request": request,
            "active_jobs": active_jobs,
            "pending_jobs": pending_jobs,
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
            "active_batches": active_batches,
        },
    )
