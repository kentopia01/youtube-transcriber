import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models.video import Video
from app.services.pipeline_recovery import get_stage_retry_limit, record_pipeline_failure
from app.services.pipeline_state import PIPELINE_STAGE_DOWNLOAD
from app.services.youtube import download_audio
from app.tasks.batch_progress import update_batch_progress_and_maybe_advance
from app.tasks.celery_app import celery
from app.tasks.helpers import get_latest_pipeline_job, update_pipeline_job

sync_engine = create_engine(settings.database_url_sync)


@celery.task(
    bind=True,
    name="tasks.download_audio",
    max_retries=get_stage_retry_limit(PIPELINE_STAGE_DOWNLOAD),
    default_retry_delay=30,
)
def download_audio_task(self, video_id: str) -> str:
    """Download audio for a video. Returns video_id for chaining."""
    vid = uuid.UUID(video_id)

    with Session(sync_engine) as db:
        video = db.get(Video, vid)
        if not video:
            raise ValueError(f"Video {video_id} not found")

        video.status = "downloading"
        job = get_latest_pipeline_job(db, vid)
        update_pipeline_job(
            job,
            task=self,
            lifecycle_status="running",
            current_stage=PIPELINE_STAGE_DOWNLOAD,
            progress_pct=5.0,
            progress_message="Downloading audio...",
            error_message=None,
            completed_at=None,
        )
        db.commit()

        try:
            result = download_audio(video.youtube_video_id, settings.audio_dir)

            duration = result.get("duration")
            max_duration = settings.max_video_duration_minutes * 60
            if duration and duration > max_duration:
                limit_min = settings.max_video_duration_minutes
                actual_min = int(duration // 60)
                raise ValueError(
                    f"Video duration {actual_min}min exceeds limit of {limit_min}min. "
                    f"Set MAX_VIDEO_DURATION_MINUTES in .env to allow longer videos."
                )

            video.audio_file_path = result["audio_path"]
            video.title = result.get("title", video.title)
            video.description = result.get("description", video.description)
            video.duration_seconds = duration
            video.thumbnail_url = result.get("thumbnail")
            video.status = "downloaded"

            update_pipeline_job(
                job,
                task=self,
                lifecycle_status="running",
                current_stage=PIPELINE_STAGE_DOWNLOAD,
                progress_pct=25.0,
                progress_message="Audio downloaded",
            )

            db.commit()
            return video_id

        except Exception as exc:
            if self.request.retries < self.max_retries:
                video.status = "downloading"
                video.error_message = f"Retrying download after error: {exc}"
                update_pipeline_job(
                    job,
                    task=self,
                    lifecycle_status="running",
                    current_stage=PIPELINE_STAGE_DOWNLOAD,
                    progress_pct=5.0,
                    progress_message=f"Retrying download ({self.request.retries + 1}/{self.max_retries})",
                    error_message=None,
                    completed_at=None,
                )
                db.commit()
                raise self.retry(exc=exc)

            record_pipeline_failure(
                db,
                job,
                task=self,
                video=video,
                stage=PIPELINE_STAGE_DOWNLOAD,
                error=exc,
                default_message=f"Download failed: {exc}",
            )
            if job and job.batch_id:
                update_batch_progress_and_maybe_advance(db, job.batch_id)
            db.commit()
            raise
