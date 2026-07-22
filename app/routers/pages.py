import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_db
from app.models.batch import Batch
from app.models.channel import Channel
from app.models.chat_session import ChatSession
from app.models.job import Job
from app.models.reader_state import READER_STATUS_UNREAD, ReaderState
from app.models.reader_annotation import ReaderAnnotation
from app.models.transcription import Transcription
from app.models.transcription_segment import TranscriptionSegment
from app.models.video import Video
from app.services.operations_dashboard import (
    build_operations_summary,
    classify_batch_warning,
    load_channel_video_counts,
)
from app.services.reader import build_reader_blocks, build_reader_outline, reader_state_dict

reader_router = APIRouter(tags=["reader-pages"])
operations_router = APIRouter(prefix="/ops", tags=["operations-pages"])
router = APIRouter(tags=["legacy-pages"])


def _redirect_with_query(request: Request, target: str) -> RedirectResponse:
    query = request.url.query
    path_and_query, fragment = (target.split("#", 1) + [""])[:2]
    separator = "&" if "?" in path_and_query else "?"
    location = f"{path_and_query}{separator}{query}" if query else path_and_query
    if fragment:
        location = f"{location}#{fragment}"
    return RedirectResponse(url=location, status_code=307)


def _reader_card(video: Video, state: ReaderState | None) -> dict:
    transcription = getattr(video, "transcription", None)
    summary = getattr(video, "summary", None)
    report = getattr(video, "report", None)
    word_count = transcription.word_count if transcription else 0
    return {
        "video": video,
        "state": state,
        "progress_pct": float(state.progress_pct or 0) if state else 0.0,
        "reading_minutes": max(1, round((word_count or 0) / 225)),
        "summary_preview": (
            (summary.content[:220] + ("…" if len(summary.content) > 220 else ""))
            if summary and summary.content
            else None
        ),
        "report_ready": bool(report and report.delivery_status == "delivered"),
    }


@reader_router.get("/")
async def reader_home(request: Request, db: AsyncSession = Depends(get_db)):
    local_owner = ReaderState.digest_lane_id.is_(None)
    state_options = selectinload(ReaderState.video).options(
        selectinload(Video.channel),
        selectinload(Video.transcription),
        selectinload(Video.summary),
        selectinload(Video.report),
    )
    continue_result = await db.execute(
        select(ReaderState)
        .options(state_options)
        .where(
            local_owner,
            ReaderState.status == "reading",
            ReaderState.progress_pct > 0,
            ReaderState.progress_pct < 100,
        )
        .order_by(ReaderState.last_read_at.desc().nullslast())
        .limit(8)
    )
    continue_states = continue_result.scalars().all()

    local_join = and_(ReaderState.video_id == Video.id, local_owner)
    recent_result = await db.execute(
        select(Video, ReaderState)
        .outerjoin(ReaderState, local_join)
        .options(
            selectinload(Video.channel),
            selectinload(Video.transcription),
            selectinload(Video.summary),
            selectinload(Video.report),
        )
        .where(
            Video.status == "completed",
            or_(ReaderState.id.is_(None), ReaderState.status == "unread"),
        )
        .order_by(Video.updated_at.desc())
        .limit(12)
    )
    recent_rows = recent_result.all()

    later_result = await db.execute(
        select(ReaderState)
        .options(state_options)
        .where(local_owner, ReaderState.status == "later")
        .order_by(ReaderState.updated_at.desc())
        .limit(8)
    )
    later_states = later_result.scalars().all()

    queue_probe = getattr(request.app.state, "operations_queue_probe", None)
    operations = await build_operations_summary(db, queue_probe=queue_probe)
    return request.app.state.templates.TemplateResponse(
        request,
        "reader_home.html",
        {
            "request": request,
            "continue_items": [_reader_card(state.video, state) for state in continue_states],
            "recent_items": [_reader_card(video, state) for video, state in recent_rows],
            "later_items": [_reader_card(state.video, state) for state in later_states],
            "operations": operations,
        },
    )


@operations_router.get("")
@operations_router.get("/", include_in_schema=False)
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

    queue_probe = getattr(request.app.state, "operations_queue_probe", None)
    operations = await build_operations_summary(db, queue_probe=queue_probe)

    return request.app.state.templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "jobs": jobs,
            "active_jobs": active_jobs,
            "operations": operations,
            "total_videos": operations.counts.total_videos,
            "completed_videos": operations.counts.completed_videos,
            "total_channels": operations.counts.total_channels,
            "pending_jobs": pending_jobs,
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
            "failed_total": operations.counts.failed_visible_jobs,
            "in_flight_total": operations.counts.in_flight_jobs,
            "active_batches": operations.active_batches,
            "batch_warning_map": operations.batch_warning_map,
        },
    )


@operations_router.get("/partials/recent-jobs")
async def recent_jobs_partial(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Job).options(selectinload(Job.video)).order_by(Job.created_at.desc()).limit(10)
    )
    jobs = result.scalars().all()
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/recent_jobs.html", {"request": request, "jobs": jobs}
    )


@reader_router.get("/read")
async def library_page(
    request: Request,
    tab: str = "videos",
    page: int = 1,
    status: str | None = None,
    length: str | None = None,
    channel_id: uuid.UUID | None = None,
    sort: str = "recent",
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    per_page = 20
    offset = (page - 1) * per_page

    # Videos
    local_join = and_(
        ReaderState.video_id == Video.id,
        ReaderState.digest_lane_id.is_(None),
    )
    filters = []
    if status == "unread":
        filters.append(or_(ReaderState.id.is_(None), ReaderState.status == "unread"))
    elif status in {"reading", "later", "finished", "archived"}:
        filters.append(ReaderState.status == status)
    if length == "quick":
        filters.append(Video.duration_seconds <= 1200)
    elif length == "long":
        filters.append(Video.duration_seconds >= 2700)
    if channel_id:
        filters.append(Video.channel_id == channel_id)
    if q:
        filters.append(Video.title.ilike(f"%{q.strip()}%"))

    count_query = select(func.count(Video.id)).outerjoin(ReaderState, local_join)
    video_query = (
        select(Video)
        .outerjoin(ReaderState, local_join)
        .options(
            selectinload(Video.channel),
            selectinload(Video.transcription),
            selectinload(Video.summary),
            selectinload(Video.report),
        )
    )
    # The Reader library owns readable documents. Pipeline records that are not
    # complete remain available in Operations and the legacy-compatible video
    # list, but must not lead to dead Reader links here.
    filters.append(Video.status == "completed")
    if filters:
        count_query = count_query.where(*filters)
        video_query = video_query.where(*filters)
    order = {
        "title": Video.title.asc(),
        "shortest": Video.duration_seconds.asc().nullslast(),
        "longest": Video.duration_seconds.desc().nullslast(),
        "progress": ReaderState.last_read_at.desc().nullslast(),
    }.get(sort, Video.created_at.desc())
    video_query = video_query.order_by(order)
    video_count = await db.scalar(count_query) or 0
    video_result = await db.execute(video_query.offset(offset).limit(per_page))
    videos = video_result.scalars().all()
    state_result = await db.execute(
        select(ReaderState).where(
            ReaderState.video_id.in_([video.id for video in videos]),
            ReaderState.digest_lane_id.is_(None),
        )
    ) if videos else None
    video_state_map = {
        state.video_id: state for state in state_result.scalars().all()
    } if state_result else {}
    video_card_map = {
        video.id: _reader_card(video, video_state_map.get(video.id)) for video in videos
    }
    total_video_pages = (video_count + per_page - 1) // per_page

    # Channels
    channel_result = await db.execute(select(Channel).order_by(Channel.name))
    channels = channel_result.scalars().all()
    channel_video_counts = await load_channel_video_counts(db)

    return request.app.state.templates.TemplateResponse(
        request,
        "library.html",
        {
            "request": request,
            "tab": tab,
            "videos": videos,
            "channels": channels,
            "channel_video_counts": channel_video_counts,
            "video_state_map": video_state_map,
            "video_card_map": video_card_map,
            "video_count": video_count,
            "page": page,
            "total_pages": total_video_pages,
            "status_filter": status,
            "length_filter": length,
            "channel_filter": channel_id,
            "sort_filter": sort,
            "query_filter": q or "",
        },
    )


@reader_router.get("/read/videos")
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


@reader_router.get("/read/highlights")
async def reader_highlights(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ReaderAnnotation)
        .options(
            selectinload(ReaderAnnotation.video).selectinload(Video.channel)
        )
        .where(ReaderAnnotation.digest_lane_id.is_(None))
        .order_by(ReaderAnnotation.updated_at.desc())
    )
    return request.app.state.templates.TemplateResponse(
        request,
        "reader_highlights.html",
        {"request": request, "annotations": result.scalars().all()},
    )


@reader_router.get("/read/{video_id}")
async def reader_document(request: Request, video_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Video)
        .options(
            selectinload(Video.channel),
            selectinload(Video.transcription).selectinload(Transcription.segments),
        )
        .where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        return request.app.state.templates.TemplateResponse(
            request,
            "error.html",
            {"request": request, "message": "Video not found"},
            status_code=404,
        )
    if not video.transcription:
        return request.app.state.templates.TemplateResponse(
            request,
            "error.html",
            {"request": request, "message": "Readable transcript not found"},
            status_code=404,
        )
    blocks = build_reader_blocks(
        video.transcription.segments,
        full_text=video.transcription.full_text,
        duration_seconds=video.duration_seconds,
    )
    if not blocks:
        return request.app.state.templates.TemplateResponse(
            request,
            "error.html",
            {"request": request, "message": "Transcript has no readable content"},
            status_code=422,
        )
    state_result = await db.execute(
        select(ReaderState).where(
            ReaderState.video_id == video_id,
            ReaderState.digest_lane_id.is_(None),
        )
    )
    state = state_result.scalar_one_or_none()
    if state is None:
        state = ReaderState(
            video_id=video_id,
            status=READER_STATUS_UNREAD,
            progress_pct=0.0,
        )
        db.add(state)
    now = datetime.now(timezone.utc)
    state.last_read_at = now
    video.last_activity_at = now
    await db.commit()
    total_words = sum(block.word_count for block in blocks)
    return request.app.state.templates.TemplateResponse(
        request,
        "reader_document.html",
        {
            "request": request,
            "video": video,
            "transcription": video.transcription,
            "blocks": blocks,
            "outline": build_reader_outline(blocks),
            "reader_state": reader_state_dict(state, blocks),
            "estimated_reading_minutes": max(1, round(total_words / 225)),
        },
    )


@reader_router.get("/read/{video_id}/details")
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
    summary_html = None
    if summary:
        from app.services.reporting import markdownish_to_safe_html

        summary_html = markdownish_to_safe_html(summary.content)

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
            "summary_html": summary_html,
            "latest_job": latest_job,
        },
    )


@reader_router.get("/read/channels/{channel_id}")
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
    channel_video_count = len(videos)

    persona = await get_persona(db, SCOPE_CHANNEL, str(channel_id))
    completed_videos = await count_completed_videos(db, channel_id)

    return request.app.state.templates.TemplateResponse(
        request,
        "channel_detail.html",
        {
            "request": request,
            "channel": channel,
            "videos": videos,
            "channel_video_count": channel_video_count,
            "persona": persona,
            "completed_videos": completed_videos,
            "persona_min_videos": _s.persona_min_videos,
        },
    )


@reader_router.get("/read/channels/{channel_id}/chat")
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
async def chat_page(
    request: Request,
    video_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
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

    channels_result = await db.execute(select(Channel).order_by(Channel.name))
    channels = channels_result.scalars().all()

    searchable_video_count = await db.scalar(
        select(func.count(Video.id)).where(Video.status == "completed")
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
            "active_video_count": searchable_video_count,
            "channels": channels,
            "scope_video_id": video_id,
        },
    )


@router.get("/chat/{session_id}")
async def chat_session_page(
    request: Request,
    session_id: uuid.UUID,
    video_id: uuid.UUID | None = None,
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

    channels_result = await db.execute(select(Channel).order_by(Channel.name))
    channels = channels_result.scalars().all()

    searchable_video_count = await db.scalar(
        select(func.count(Video.id)).where(Video.status == "completed")
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
            "active_video_count": searchable_video_count,
            "channels": channels,
            "scope_video_id": video_id,
        },
    )


@router.get("/search")
async def search_page(
    request: Request,
    video_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    channels_result = await db.execute(select(Channel).order_by(Channel.name))
    channels = channels_result.scalars().all()
    return request.app.state.templates.TemplateResponse(
        request,
        "search.html",
        {"request": request, "channels": channels, "scope_video_id": video_id},
    )


@router.get("/global-search")
async def global_search_page(request: Request):
    return _redirect_with_query(request, "/search")


@operations_router.get("/jobs/{job_id}")
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


@operations_router.get("/queue")
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
    failed_total = int(
        await db.scalar(
            select(func.count(Job.id))
            .join(Video, Video.id == Job.video_id)
            .where(
                Job.status == "failed",
                Job.hidden_from_queue.is_(False),
                Video.dismissed_at.is_(None),
            )
        )
        or 0
    )

    # Active batches
    batch_result = await db.execute(
        select(Batch)
        .options(selectinload(Batch.jobs))
        .where(Batch.status.in_(["pending", "running"]))
        .order_by(Batch.created_at)
    )
    active_batches = batch_result.scalars().all()
    batch_warning_map = {
        batch.id: warning
        for batch in active_batches
        if (warning := classify_batch_warning(batch)) is not None
    }

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
                "failed_total": failed_total,
                "in_flight_total": len(active_jobs) + len(pending_jobs),
                "active_batches": active_batches,
                "batch_warning_map": batch_warning_map,
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
            "failed_total": failed_total,
            "in_flight_total": len(active_jobs) + len(pending_jobs),
            "active_batches": active_batches,
            "batch_warning_map": batch_warning_map,
        },
    )


# Compatibility routes keep existing bookmarks working while canonical page
# ownership moves under Reader and Operations. API routes are intentionally
# unchanged.
@router.get("/submit")
async def legacy_submit(request: Request):
    return _redirect_with_query(request, "/ops#submit-video")


@router.get("/partials/recent-jobs")
async def legacy_recent_jobs(request: Request):
    return _redirect_with_query(request, "/ops/partials/recent-jobs")


@router.get("/library")
async def legacy_library(request: Request):
    return _redirect_with_query(request, "/read")


@router.get("/videos")
async def legacy_videos(request: Request):
    return _redirect_with_query(request, "/read/videos")


@router.get("/videos/{video_id}")
async def legacy_video_detail(request: Request, video_id: uuid.UUID):
    return _redirect_with_query(request, f"/read/{video_id}")


@router.get("/channels")
async def channel_list(request: Request):
    return _redirect_with_query(request, "/read?tab=channels")


@router.get("/channels/{channel_id}")
async def legacy_channel_detail(request: Request, channel_id: uuid.UUID):
    return _redirect_with_query(request, f"/read/channels/{channel_id}")


@router.get("/channels/{channel_id}/chat")
async def legacy_channel_chat(request: Request, channel_id: uuid.UUID):
    return _redirect_with_query(request, f"/read/channels/{channel_id}/chat")


@router.get("/jobs/{job_id}")
async def legacy_job_detail(request: Request, job_id: uuid.UUID):
    return _redirect_with_query(request, f"/ops/jobs/{job_id}")


@router.get("/queue")
async def legacy_queue(request: Request):
    return _redirect_with_query(request, "/ops/queue")
