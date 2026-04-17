"""Celery task for LLM-powered transcript cleanup.

Sends transcript through Anthropic Haiku for cleanup/correction.
Runs after diarization (if enabled) or after transcription (if diarization disabled).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models.transcription import Transcription
from app.services.pipeline_recovery import record_pipeline_failure
from app.services.pipeline_state import PIPELINE_STAGE_CLEANUP
from app.services.transcript_cleanup import clean_transcript
from app.tasks.batch_progress import update_batch_progress_and_maybe_advance
from app.tasks.celery_app import celery
from app.tasks.helpers import get_pipeline_job_context, update_pipeline_job

sync_engine = create_engine(settings.database_url_sync)


@celery.task(bind=True, name="tasks.cleanup_transcript")
def cleanup_transcript_task(self, payload: dict[str, str] | str) -> dict[str, str] | str:
    """Clean up a video's transcript using LLM.

    Skips if transcript cleanup is disabled.
    Returns payload for chaining.
    """
    if not settings.transcript_cleanup_enabled:
        return payload

    if not settings.anthropic_api_key:
        import structlog

        structlog.get_logger().warn(
            "transcript_cleanup_skipped",
            reason="ANTHROPIC_API_KEY not set",
            payload=payload,
        )
        return payload

    with Session(sync_engine) as db:
        payload, video, job = get_pipeline_job_context(
            db,
            payload,
            expected_stage=PIPELINE_STAGE_CLEANUP,
            require_transcription=True,
        )
        vid = video.id

        from app.services.cost_tracker import set_cost_source, source_for_attempt_reason
        set_cost_source(source_for_attempt_reason(getattr(job, "attempt_creation_reason", None)))

        transcription = db.query(Transcription).filter(
            Transcription.video_id == vid
        ).first()
        if not transcription:
            raise ValueError(f"No transcription found for video {vid}")

        update_pipeline_job(
            job,
            task=self,
            lifecycle_status="running",
            current_stage=PIPELINE_STAGE_CLEANUP,
            progress_pct=70.0,
            progress_message="Cleaning transcript with Haiku…",
        )
        db.commit()

        try:
            segment_payload = [
                {
                    "start": segment.start_time,
                    "end": segment.end_time,
                    "text": segment.text,
                    "confidence": segment.confidence,
                    "speaker": segment.speaker,
                }
                for segment in transcription.segments
            ]
            cleaned_segments = clean_transcript(
                segment_payload,
                api_key=settings.anthropic_api_key,
                model=settings.anthropic_cleanup_model,
            )

            for segment_model, cleaned in zip(transcription.segments, cleaned_segments):
                segment_model.text = cleaned.get("text", segment_model.text)
                if "speaker" in cleaned:
                    segment_model.speaker = cleaned.get("speaker")

            transcription.full_text = " ".join(
                segment.text.strip()
                for segment in transcription.segments
                if segment.text and segment.text.strip()
            )
            video.status = "cleaned"

            update_pipeline_job(
                job,
                task=self,
                lifecycle_status="running",
                current_stage=PIPELINE_STAGE_CLEANUP,
                progress_pct=75.0,
                progress_message="Transcript cleaned, continuing pipeline",
            )
            db.commit()
            return payload
        except Exception as exc:
            record_pipeline_failure(
                db,
                job,
                task=self,
                video=video,
                stage=PIPELINE_STAGE_CLEANUP,
                error=exc,
                default_message=f"Transcript cleanup failed: {exc}",
            )
            if job and job.batch_id:
                update_batch_progress_and_maybe_advance(db, job.batch_id)
            db.commit()
            raise
