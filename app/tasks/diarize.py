"""Celery task for speaker diarization and alignment.

Runs pyannote.audio diarization + whisperX alignment on an already-transcribed
video, then updates segment records with speaker labels.
"""

import uuid

import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models.transcription import Transcription
from app.models.video import Video
from app.services.alignment import align_and_merge
from app.services.diarization import diarize
from app.services.pipeline_recovery import record_pipeline_failure
from app.services.pipeline_state import PIPELINE_STAGE_DIARIZE
from app.tasks.batch_progress import update_batch_progress_and_maybe_advance
from app.tasks.celery_app import celery
from app.tasks.helpers import get_pipeline_job_context, update_pipeline_job

sync_engine = create_engine(settings.database_url_sync)
logger = structlog.get_logger()


@celery.task(bind=True, name="tasks.diarize_and_align")
def diarize_and_align_task(self, payload: dict[str, str] | str) -> dict[str, str] | str:
    """Run diarization and alignment on a transcribed video.

    Skips if diarization is disabled or HF token is not set.
    Returns payload for chaining.
    """
    # Skip if disabled
    if not settings.diarization_enabled:
        return payload

    if not settings.hf_token:
        logger.warning(
            "diarization_skipped",
            reason="HF_TOKEN not set",
            payload=payload,
        )
        return payload

    with Session(sync_engine) as db:
        payload, video, job = get_pipeline_job_context(
            db,
            payload,
            expected_stage=PIPELINE_STAGE_DIARIZE,
            require_audio=True,
            require_transcription=True,
        )
        vid = video.id

        transcription = db.query(Transcription).filter(
            Transcription.video_id == vid
        ).first()
        if not transcription:
            raise ValueError(f"No transcription found for video {vid}")
        update_pipeline_job(
            job,
            task=self,
            lifecycle_status="running",
            current_stage=PIPELINE_STAGE_DIARIZE,
            progress_pct=52.0,
            progress_message="Running speaker diarization...",
            completed_at=None,
        )
        db.commit()

        try:
            # Get transcript segments
            segments = [
                {
                    "start": s.start_time,
                    "end": s.end_time,
                    "text": s.text,
                    "confidence": s.confidence,
                }
                for s in transcription.segments
            ]

            # Run diarization
            diarization_segments = diarize(
                video.audio_file_path,
                hf_token=settings.hf_token,
            )

            update_pipeline_job(
                job,
                task=self,
                lifecycle_status="running",
                current_stage=PIPELINE_STAGE_DIARIZE,
                progress_pct=58.0,
                progress_message="Aligning speakers with transcript...",
            )
            db.commit()

            # Align and merge
            aligned_segments = align_and_merge(
                audio_path=video.audio_file_path,
                transcript_segments=segments,
                diarization_segments=diarization_segments,
                language=transcription.language or "en",
            )

            # Update segment records with speaker labels
            for seg_model, aligned in zip(transcription.segments, aligned_segments):
                seg_model.speaker = aligned.get("speaker")

            update_pipeline_job(
                job,
                task=self,
                lifecycle_status="running",
                current_stage=PIPELINE_STAGE_DIARIZE,
                progress_pct=65.0,
                progress_message="Speaker diarization complete",
            )
            db.commit()

            # Keep audio on disk for retryable execution and safer resume behavior.
            logger.info("audio_file_retained_for_retry", path=video.audio_file_path)

            return payload

        except Exception as exc:
            record_pipeline_failure(
                db,
                job,
                task=self,
                video=video,
                stage=PIPELINE_STAGE_DIARIZE,
                error=exc,
                default_message=f"Diarization failed: {exc}",
            )
            if job and job.batch_id:
                update_batch_progress_and_maybe_advance(db, job.batch_id)
            db.commit()
            raise
