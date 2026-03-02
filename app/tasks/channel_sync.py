import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models.channel import Channel
from app.models.job import Job
from app.services.youtube import discover_channel_videos
from app.tasks.celery_app import celery

sync_engine = create_engine(settings.database_url_sync)


@celery.task(bind=True, name="tasks.sync_channel")
def sync_channel_task(self, channel_id: str) -> dict:
    """Discover all videos from a channel. Returns channel info and video list."""
    cid = uuid.UUID(channel_id)

    with Session(sync_engine) as db:
        channel = db.get(Channel, cid)
        if not channel:
            raise ValueError(f"Channel {channel_id} not found")

        job = db.query(Job).filter(Job.channel_id == cid, Job.job_type == "channel_sync").order_by(Job.created_at.desc()).first()
        if job:
            job.status = "running"
            job.progress_pct = 10.0
            job.progress_message = "Discovering videos..."
            job.started_at = datetime.now(UTC)
        db.commit()

        try:
            result = discover_channel_videos(channel.url)

            channel.name = result.get("channel_name", channel.name)
            channel.description = result.get("description", channel.description)
            channel.thumbnail_url = result.get("thumbnail", channel.thumbnail_url)
            channel.video_count = len(result.get("videos", []))
            channel.last_synced_at = datetime.now(UTC)

            if job:
                job.status = "completed"
                job.progress_pct = 100.0
                job.progress_message = f"Found {channel.video_count} videos"
                job.completed_at = datetime.now(UTC)

            db.commit()

            return {
                "channel_id": channel_id,
                "channel_name": channel.name,
                "videos": result.get("videos", []),
            }

        except Exception as exc:
            if job:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(UTC)
            db.commit()
            raise
