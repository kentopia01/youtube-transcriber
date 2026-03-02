import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_db
from app.models.batch import Batch
from app.models.channel import Channel
from app.models.job import Job
from app.models.transcription import Transcription
from app.models.transcription_segment import TranscriptionSegment
from app.models.video import Video

router = APIRouter()


@router.get("/")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    # Recent jobs
    result = await db.execute(
        select(Job).order_by(Job.created_at.desc()).limit(10)
    )
    jobs = result.scalars().all()

    # Active/pending jobs for queue widget
    active_result = await db.execute(
        select(Job).where(Job.status.in_(["running", "queued", "pending"])).order_by(Job.created_at.desc()).limit(5)
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
        select(Job).where(Job.status.in_(["pending", "queued"])).order_by(Job.created_at).limit(20)
    )
    pending_jobs = pending_result.scalars().all()

    completed_result = await db.execute(
        select(Job).where(Job.status == "completed").order_by(Job.completed_at.desc()).limit(10)
    )
    completed_jobs = completed_result.scalars().all()

    failed_result = await db.execute(
        select(Job).where(Job.status == "failed").order_by(Job.completed_at.desc()).limit(10)
    )
    failed_jobs = failed_result.scalars().all()

    batch_result = await db.execute(
        select(Batch).where(Batch.status.in_(["pending", "running"])).order_by(Batch.created_at)
    )
    active_batches = batch_result.scalars().all()

    return request.app.state.templates.TemplateResponse(
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

    return request.app.state.templates.TemplateResponse(
        "video_detail.html",
        {
            "request": request,
            "video": video,
            "transcription": transcription,
            "summary": summary,
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
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        return request.app.state.templates.TemplateResponse(
            "error.html", {"request": request, "message": "Channel not found"}, status_code=404
        )

    videos_result = await db.execute(
        select(Video)
        .where(Video.channel_id == channel_id)
        .order_by(Video.published_at.desc().nullslast())
    )
    videos = videos_result.scalars().all()

    return request.app.state.templates.TemplateResponse(
        "channel_detail.html",
        {"request": request, "channel": channel, "videos": videos},
    )


@router.get("/search")
async def search_page(request: Request):
    return request.app.state.templates.TemplateResponse(
        "search.html", {"request": request}
    )


@router.get("/jobs/{job_id}")
async def job_detail(request: Request, job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        return request.app.state.templates.TemplateResponse(
            "error.html", {"request": request, "message": "Job not found"}, status_code=404
        )

    video = None
    if job.video_id:
        v_result = await db.execute(select(Video).where(Video.id == job.video_id))
        video = v_result.scalar_one_or_none()

    # For HTMX polling, return partial
    if request.headers.get("HX-Request"):
        return request.app.state.templates.TemplateResponse(
            "partials/job_status.html",
            {"request": request, "job": job, "video": video},
        )

    return request.app.state.templates.TemplateResponse(
        "job_detail.html", {"request": request, "job": job, "video": video}
    )


@router.get("/queue")
async def queue_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Queue data endpoint — serves both full page and HTMX partials."""
    # Active jobs
    active_result = await db.execute(
        select(Job).where(Job.status == "running").order_by(Job.started_at.desc())
    )
    active_jobs = active_result.scalars().all()

    # Pending jobs
    pending_result = await db.execute(
        select(Job).where(Job.status.in_(["pending", "queued"])).order_by(Job.created_at)
    )
    pending_jobs = pending_result.scalars().all()

    # Recent completed
    completed_result = await db.execute(
        select(Job).where(Job.status == "completed").order_by(Job.completed_at.desc()).limit(20)
    )
    completed_jobs = completed_result.scalars().all()

    # Failed
    failed_result = await db.execute(
        select(Job).where(Job.status == "failed").order_by(Job.completed_at.desc()).limit(20)
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
