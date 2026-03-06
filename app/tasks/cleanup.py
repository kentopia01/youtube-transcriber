"""Celery task for LLM-powered transcript cleanup.

Sends transcript through Anthropic Haiku for filler word removal and
grammar cleanup. Speaker-aware. Runs after diarization, before summarization.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models.job import Job
from app.models.transcription import Transcription
from app.models.video import Video
from app.services.transcript_cleanup import clean_transcript
from app.tasks.batch_progress import update_batch_progress_and_maybe_advance
from app.tasks.celery_app import celery
from app.tasks.helpers import get_latest_pipeline_job

sync_engine = create_engine(settings.database_url_sync)


@celery.task(bind=True, name="tasks.cleanup_transcript")
def cleanup_transcript_task(self, video_id: str) -> str:
    """Clean up a video's transcript using LLM.

    Skips if transcript cleanup is disabled.
    Returns video_id for chaining.
    """
    vid = uuid.UUID(video_id)

    # Skip if disabled
    if not settings.transcript_cleanup_enabled:
        return video_id

    if not settings.anthropic_api_key:
        import structlog
        structlog.get_logger().warn(
            "transcript_cleanup_skipped",
            reason="ANTHROPIC_API_KEY not set",
            video_id=video_id,
        )
        return video_id

    with Session(sync_engine) as db:
        video = db.get(Video, vid)
        if not video:
            raise ValueError(f"Video {video_id} not found")

        transcription = db.query(Transcription).filter(
            Transcription.video_id == vid
        ).first()
        if not transcription:
            raise ValueError(f"No transcription found for video {video_id}")

        job = get_latest_pipeline_job(db, vid)
        if job:
            job.progress_pct = 67.0
            job.progress_message = "Cleaning transcript with LLM..."
        db.commit()

        try:
            # Build segment data
            segments = [
                {
                    "text": s.text,
                    "speaker": s.speaker,
                    "start": s.start_time,
                    "end": s.end_time,
                    "confidence": s.confidence,
                }
                for s in transcription.segments
            ]

            # Run LLM cleanup
            cleaned_segments = clean_transcript(
                segments,
                api_key=settings.anthropic_api_key,
                model=settings.cleanup_model,
            )

            # Update segment text in DB
            for seg_model, cleaned in zip(transcription.segments, cleaned_segments):
                seg_model.text = cleaned["text"]

            # Rebuild full_text from cleaned segments
            full_text_parts = [s["text"] for s in cleaned_segments]
            transcription.full_text = " ".join(full_text_parts)
            transcription.word_count = len(transcription.full_text.split())

            if job:
                job.progress_pct = 72.0
                job.progress_message = "Transcript cleanup complete"
            db.commit()

            return video_id

        except Exception as exc:
            # Don't fail the pipeline on cleanup errors — log and continue
            import structlog
            structlog.get_logger().error(
                "transcript_cleanup_failed",
                error=str(exc),
                video_id=video_id,
            )
            if job:
                job.progress_message = f"Cleanup failed (continuing): {exc}"
            db.commit()
            return video_id
