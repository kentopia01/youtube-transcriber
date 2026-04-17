import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models.summary import Summary
from app.models.transcription import Transcription
from app.models.video import Video
from app.services.pipeline_recovery import get_stage_retry_limit, record_pipeline_failure
from app.services.pipeline_state import PIPELINE_STAGE_SUMMARIZE
from app.services.summarization import summarize_text
from app.tasks.batch_progress import update_batch_progress_and_maybe_advance
from app.tasks.celery_app import celery
from app.tasks.helpers import get_pipeline_job_context, update_pipeline_job

sync_engine = create_engine(settings.database_url_sync)


@celery.task(
    bind=True,
    name="tasks.summarize_transcription",
    max_retries=get_stage_retry_limit(PIPELINE_STAGE_SUMMARIZE),
    default_retry_delay=10,
)
def summarize_transcription_task(self, payload: dict[str, str] | str) -> dict[str, str] | str:
    """Summarize a video's transcription. Returns payload for chaining."""
    with Session(sync_engine) as db:
        payload, video, job = get_pipeline_job_context(
            db,
            payload,
            expected_stage=PIPELINE_STAGE_SUMMARIZE,
            require_transcription=True,
        )
        vid = video.id

        from app.services.cost_tracker import set_cost_source, source_for_attempt_reason
        set_cost_source(source_for_attempt_reason(getattr(job, "attempt_creation_reason", None)))

        transcription = db.query(Transcription).filter(Transcription.video_id == vid).first()
        if not transcription:
            raise ValueError(f"No transcription found for video {vid}")

        video.status = "summarizing"
        update_pipeline_job(
            job,
            task=self,
            lifecycle_status="running",
            current_stage=PIPELINE_STAGE_SUMMARIZE,
            progress_pct=76.0,
            progress_message="Generating summary...",
            completed_at=None,
        )
        db.commit()

        try:
            result = summarize_text(
                transcription.full_text,
                video_title=video.title,
                api_key=settings.anthropic_api_key,
                model=settings.summary_model,
            )

            # Upsert: update existing summary or create new one
            existing_summary = db.query(Summary).filter(
                Summary.video_id == vid
            ).first()
            if existing_summary:
                existing_summary.content = result["summary"]
                existing_summary.model = result.get("model")
                existing_summary.prompt_tokens = result.get("prompt_tokens")
                existing_summary.completion_tokens = result.get("completion_tokens")
            else:
                summary = Summary(
                    video_id=vid,
                    content=result["summary"],
                    model=result.get("model"),
                    prompt_tokens=result.get("prompt_tokens"),
                    completion_tokens=result.get("completion_tokens"),
                )
                db.add(summary)

            video.status = "summarized"
            update_pipeline_job(
                job,
                task=self,
                lifecycle_status="running",
                current_stage=PIPELINE_STAGE_SUMMARIZE,
                progress_pct=90.0,
                progress_message="Summary generated",
            )

            db.commit()
            return payload

        except Exception as exc:
            if self.request.retries < self.max_retries:
                backoff = 10 * (2 ** self.request.retries)  # 10s, 20s
                video.status = "summarizing"
                video.error_message = f"Retrying summarization after error: {exc}"
                update_pipeline_job(
                    job,
                    task=self,
                    lifecycle_status="running",
                    current_stage=PIPELINE_STAGE_SUMMARIZE,
                    progress_message=f"Retrying summary ({self.request.retries + 1}/{self.max_retries})",
                    error_message=None,
                    completed_at=None,
                )
                db.commit()
                raise self.retry(exc=exc, countdown=backoff)

            record_pipeline_failure(
                db,
                job,
                task=self,
                video=video,
                stage=PIPELINE_STAGE_SUMMARIZE,
                error=exc,
                default_message=f"Summary failed: {exc}",
            )
            if job and job.batch_id:
                update_batch_progress_and_maybe_advance(db, job.batch_id)
            db.commit()
            raise
