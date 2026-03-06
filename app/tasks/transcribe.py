import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models.job import Job
from app.models.transcription import Transcription
from app.models.transcription_segment import TranscriptionSegment
from app.models.video import Video
from app.services.transcription import transcribe_audio
from app.tasks.batch_progress import update_batch_progress_and_maybe_advance
from app.tasks.celery_app import celery
from app.tasks.helpers import get_latest_pipeline_job

sync_engine = create_engine(settings.database_url_sync)


@celery.task(bind=True, name="tasks.transcribe_audio")
def transcribe_audio_task(self, video_id: str) -> str:
    """Transcribe audio for a video. Returns video_id for chaining."""
    vid = uuid.UUID(video_id)

    with Session(sync_engine) as db:
        video = db.get(Video, vid)
        if not video:
            raise ValueError(f"Video {video_id} not found")

        video.status = "transcribing"
        job = get_latest_pipeline_job(db, vid)
        if job:
            job.progress_pct = 30.0
            job.progress_message = "Transcribing audio..."
        db.commit()

        try:
            result = transcribe_audio(
                video.audio_file_path,
                engine_type=settings.transcription_engine,
                # MLX options
                whisper_model=settings.whisper_model,
                whisper_detect_model=settings.whisper_detect_model,
                whisper_language=settings.whisper_language,
                # Faster-whisper options
                model_size=settings.whisper_model_size,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
                model_cache_dir=settings.model_cache_dir,
            )

            # Determine model name for recording
            model_name = (
                settings.whisper_model
                if settings.transcription_engine == "mlx"
                else settings.whisper_model_size
            )

            # Upsert: update existing transcription or create new one
            existing_transcription = db.query(Transcription).filter(
                Transcription.video_id == vid
            ).first()
            if existing_transcription:
                transcription = existing_transcription
                transcription.full_text = result["text"]
                transcription.language = result.get("language")
                transcription.model_size = model_name
                transcription.word_count = len(result["text"].split())
                transcription.processing_time_seconds = float(result["processing_time"]) if result.get("processing_time") is not None else None
                # Delete old segments before inserting new ones
                db.query(TranscriptionSegment).filter(
                    TranscriptionSegment.transcription_id == transcription.id
                ).delete()
                db.flush()
            else:
                transcription = Transcription(
                    video_id=vid,
                    full_text=result["text"],
                    language=result.get("language"),
                    model_size=model_name,
                    word_count=len(result["text"].split()),
                    processing_time_seconds=float(result["processing_time"]) if result.get("processing_time") is not None else None,
                )
                db.add(transcription)
                db.flush()

            for i, seg in enumerate(result.get("segments", [])):
                segment = TranscriptionSegment(
                    transcription_id=transcription.id,
                    segment_index=i,
                    start_time=float(seg["start"]),
                    end_time=float(seg["end"]),
                    text=seg["text"],
                    confidence=float(seg["confidence"]) if seg.get("confidence") is not None else None,
                )
                db.add(segment)

            video.status = "transcribed"
            if job:
                job.progress_pct = 50.0
                job.progress_message = "Transcription complete"

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
