"""Celery task for speaker diarization and alignment.

Runs pyannote.audio diarization + whisperX alignment on an already-transcribed
video, then updates segment records with speaker labels.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models.job import Job
from app.models.transcription import Transcription
from app.models.transcription_segment import TranscriptionSegment
from app.models.video import Video
from app.services.alignment import align_and_merge
from app.services.diarization import diarize
from app.tasks.batch_progress import update_batch_progress_and_maybe_advance
from app.tasks.celery_app import celery

sync_engine = create_engine(settings.database_url_sync)


@celery.task(bind=True, name="tasks.diarize_and_align")
def diarize_and_align_task(self, video_id: str) -> str:
    """Run diarization and alignment on a transcribed video.

    Skips if diarization is disabled or HF token is not set.
    Returns video_id for chaining.
    """
    vid = uuid.UUID(video_id)

    # Skip if disabled
    if not settings.diarization_enabled:
        return video_id

    if not settings.hf_token:
        import structlog
        structlog.get_logger().warn(
            "diarization_skipped",
            reason="HF_TOKEN not set",
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

        job = db.query(Job).filter(
            Job.video_id == vid, Job.job_type == "pipeline"
        ).first()
        if job:
            job.progress_pct = 52.0
            job.progress_message = "Running speaker diarization..."
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

            if job:
                job.progress_pct = 58.0
                job.progress_message = "Aligning speakers with transcript..."
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

            if job:
                job.progress_pct = 65.0
                job.progress_message = "Speaker diarization complete"
            db.commit()

            return video_id

        except Exception as exc:
            video.status = "failed"
            video.error_message = f"Diarization failed: {exc}"
            if job:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(UTC)
                if job.batch_id:
                    update_batch_progress_and_maybe_advance(db, job.batch_id)
            db.commit()
            raise
