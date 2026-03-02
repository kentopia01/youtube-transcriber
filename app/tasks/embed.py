import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models.embedding_chunk import EmbeddingChunk
from app.models.job import Job
from app.models.transcription import Transcription
from app.models.video import Video
from app.services.embedding import chunk_and_embed
from app.tasks.batch_progress import update_batch_progress_and_maybe_advance
from app.tasks.celery_app import celery

sync_engine = create_engine(settings.database_url_sync)


@celery.task(bind=True, name="tasks.generate_embeddings")
def generate_embeddings_task(self, video_id: str) -> str:
    """Generate embeddings for a video's transcription. Returns video_id for chaining."""
    vid = uuid.UUID(video_id)

    with Session(sync_engine) as db:
        video = db.get(Video, vid)
        if not video:
            raise ValueError(f"Video {video_id} not found")

        transcription = (
            db.query(Transcription)
            .filter(Transcription.video_id == vid)
            .first()
        )
        if not transcription:
            raise ValueError(f"No transcription found for video {video_id}")

        job = db.query(Job).filter(Job.video_id == vid, Job.job_type == "pipeline").first()
        if job:
            job.progress_pct = 80.0
            job.progress_message = "Generating embeddings..."
        db.commit()

        try:
            segments = [
                {"start": s.start_time, "end": s.end_time, "text": s.text}
                for s in transcription.segments
            ]

            chunks = chunk_and_embed(
                segments,
                model_cache_dir=settings.model_cache_dir,
            )

            for chunk in chunks:
                ec = EmbeddingChunk(
                    transcription_id=transcription.id,
                    video_id=vid,
                    chunk_index=chunk["chunk_index"],
                    chunk_text=chunk["chunk_text"],
                    start_time=chunk.get("start_time"),
                    end_time=chunk.get("end_time"),
                    embedding=chunk["embedding"],
                    token_count=chunk.get("token_count"),
                )
                db.add(ec)

            video.status = "completed"
            if job:
                job.status = "completed"
                job.progress_pct = 100.0
                job.progress_message = "Processing complete"
                job.completed_at = datetime.now(UTC)
                if job.batch_id:
                    update_batch_progress_and_maybe_advance(db, job.batch_id)

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
