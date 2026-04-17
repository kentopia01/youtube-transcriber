import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models.embedding_chunk import EmbeddingChunk
from app.models.summary import Summary
from app.models.transcription import Transcription
from app.models.video import Video
from app.services.embedding import chunk_and_embed, chunk_and_embed_summary
from app.services.pipeline_recovery import get_stage_retry_limit, record_pipeline_failure
from app.services.pipeline_state import PIPELINE_STAGE_COMPLETED, PIPELINE_STAGE_EMBED
from app.tasks.batch_progress import update_batch_progress_and_maybe_advance
from app.tasks.celery_app import celery
from app.tasks.helpers import get_pipeline_job_context, update_pipeline_job

sync_engine = create_engine(settings.database_url_sync)


@celery.task(
    bind=True,
    name="tasks.generate_embeddings",
    max_retries=get_stage_retry_limit(PIPELINE_STAGE_EMBED),
    default_retry_delay=10,
)
def generate_embeddings_task(self, payload: dict[str, str] | str) -> dict[str, str] | str:
    """Generate embeddings for a video's transcription. Returns payload for chaining."""
    with Session(sync_engine) as db:
        payload, video, job = get_pipeline_job_context(
            db,
            payload,
            expected_stage=PIPELINE_STAGE_EMBED,
            require_transcription=True,
        )
        vid = video.id

        transcription = (
            db.query(Transcription)
            .filter(Transcription.video_id == vid)
            .first()
        )
        if not transcription:
            raise ValueError(f"No transcription found for video {vid}")

        # exact job context is already loaded above
        update_pipeline_job(
            job,
            task=self,
            lifecycle_status="running",
            current_stage=PIPELINE_STAGE_EMBED,
            progress_pct=93.0,
            progress_message="Generating embeddings...",
            completed_at=None,
        )
        db.commit()

        try:
            # Delete existing chunks to avoid duplicates on retry
            db.query(EmbeddingChunk).filter(
                EmbeddingChunk.video_id == vid
            ).delete()
            db.flush()

            segments = [
                {"start": s.start_time, "end": s.end_time, "text": s.text, "speaker": s.speaker}
                for s in transcription.segments
            ]

            transcript_chunks = chunk_and_embed(
                segments,
                model_cache_dir=settings.model_cache_dir,
            )
            summary = db.query(Summary).filter(Summary.video_id == vid).first()
            summary_chunks = []
            if summary and summary.content.strip():
                summary_chunks = chunk_and_embed_summary(
                    summary.content,
                    model_cache_dir=settings.model_cache_dir,
                )

            chunks = transcript_chunks + summary_chunks

            for index, chunk in enumerate(chunks):
                ec = EmbeddingChunk(
                    transcription_id=transcription.id,
                    video_id=vid,
                    chunk_index=index,
                    chunk_text=chunk["chunk_text"],
                    start_time=chunk.get("start_time"),
                    end_time=chunk.get("end_time"),
                    embedding=chunk["embedding"],
                    token_count=chunk.get("token_count"),
                    speaker=chunk.get("speaker"),
                )
                db.add(ec)

            video.status = "completed"
            update_pipeline_job(
                job,
                task=self,
                lifecycle_status="completed",
                current_stage=PIPELINE_STAGE_COMPLETED,
                progress_pct=100.0,
                progress_message="Processing complete",
            )
            if job and job.batch_id:
                update_batch_progress_and_maybe_advance(db, job.batch_id)

            db.commit()

            if video.channel_id:
                from app.tasks.generate_persona import enqueue_channel_persona

                enqueue_channel_persona(str(video.channel_id))

            try:
                from app.services.telegram_notify import notify as _tg_notify

                speakers_count = None
                if transcription and getattr(transcription, "speakers", None):
                    try:
                        speakers_count = len(transcription.speakers)
                    except TypeError:
                        speakers_count = None

                _tg_notify(
                    "video.completed",
                    {
                        "video_id": str(video.id),
                        "channel_id": str(video.channel_id) if video.channel_id else None,
                        "title": video.title,
                        "duration": video.duration_seconds,
                        "speakers": speakers_count,
                    },
                )
            except Exception:  # noqa: BLE001
                pass

            return payload

        except Exception as exc:
            if self.request.retries < self.max_retries:
                backoff = 10 * (2 ** self.request.retries)  # 10s, 20s
                video.status = "summarized"
                video.error_message = f"Retrying embeddings after error: {exc}"
                update_pipeline_job(
                    job,
                    task=self,
                    lifecycle_status="running",
                    current_stage=PIPELINE_STAGE_EMBED,
                    progress_message=f"Retrying embeddings ({self.request.retries + 1}/{self.max_retries})",
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
                stage=PIPELINE_STAGE_EMBED,
                error=exc,
                default_message=f"Embedding failed: {exc}",
            )
            if job and job.batch_id:
                update_batch_progress_and_maybe_advance(db, job.batch_id)
            db.commit()
            raise
