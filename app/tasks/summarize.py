import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models.job import Job
from app.models.summary import Summary
from app.models.transcription import Transcription
from app.models.video import Video
from app.services.summarization import summarize_text
from app.tasks.batch_progress import update_batch_progress_and_maybe_advance
from app.tasks.celery_app import celery

sync_engine = create_engine(settings.database_url_sync)


@celery.task(bind=True, name="tasks.summarize_transcription")
def summarize_transcription_task(self, video_id: str) -> str:
    """Summarize a video's transcription. Returns video_id for chaining."""
    vid = uuid.UUID(video_id)

    with Session(sync_engine) as db:
        video = db.get(Video, vid)
        if not video:
            raise ValueError(f"Video {video_id} not found")

        transcription = db.query(Transcription).filter(Transcription.video_id == vid).first()
        if not transcription:
            raise ValueError(f"No transcription found for video {video_id}")

        video.status = "summarizing"
        job = db.query(Job).filter(Job.video_id == vid, Job.job_type == "pipeline").first()
        if job:
            job.progress_pct = 55.0
            job.progress_message = "Generating summary..."
        db.commit()

        try:
            result = summarize_text(
                transcription.full_text,
                video_title=video.title,
                api_key=settings.anthropic_api_key,
                model=settings.summary_model,
            )

            summary = Summary(
                video_id=vid,
                content=result["summary"],
                model=result.get("model"),
                prompt_tokens=result.get("prompt_tokens"),
                completion_tokens=result.get("completion_tokens"),
            )
            db.add(summary)

            video.status = "summarized"
            if job:
                job.progress_pct = 75.0
                job.progress_message = "Summary generated"

            db.commit()
            return video_id

        except Exception as exc:
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
