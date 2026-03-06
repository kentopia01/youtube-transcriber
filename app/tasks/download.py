import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models.job import Job
from app.models.video import Video
from app.services.youtube import download_audio
from app.tasks.batch_progress import update_batch_progress_and_maybe_advance
from app.tasks.celery_app import celery
from app.tasks.helpers import get_latest_pipeline_job

sync_engine = create_engine(settings.database_url_sync)


@celery.task(bind=True, name="tasks.download_audio", max_retries=3, default_retry_delay=30)
def download_audio_task(self, video_id: str) -> str:
    """Download audio for a video. Returns video_id for chaining."""
    vid = uuid.UUID(video_id)

    with Session(sync_engine) as db:
        video = db.get(Video, vid)
        if not video:
            raise ValueError(f"Video {video_id} not found")

        # Update status
        video.status = "downloading"
        job = get_latest_pipeline_job(db, vid)
        if job:
            job.status = "running"
            job.progress_pct = 5.0
            job.progress_message = "Downloading audio..."
            job.started_at = datetime.now(UTC)
        db.commit()

        try:
            result = download_audio(video.youtube_video_id, settings.audio_dir)

            video.audio_file_path = result["audio_path"]
            video.title = result.get("title", video.title)
            video.description = result.get("description", video.description)
            video.duration_seconds = result.get("duration")
            video.thumbnail_url = result.get("thumbnail")
            video.status = "downloaded"

            if job:
                job.progress_pct = 25.0
                job.progress_message = "Audio downloaded"

            db.commit()
            return video_id

        except Exception as exc:
            if self.request.retries < self.max_retries:
                video.status = "pending"
                video.error_message = f"Retrying download after error: {exc}"
                if job:
                    job.status = "queued"
                    job.progress_message = f"Retrying download ({self.request.retries + 1}/{self.max_retries})"
                    job.error_message = None
                    job.completed_at = None
                db.commit()
                raise self.retry(exc=exc)

            video.status = "failed"
            video.error_message = str(exc)
            if job:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(UTC)
                if job.batch_id:
                    update_batch_progress_and_maybe_advance(db, job.batch_id)
            db.commit()
            raise
