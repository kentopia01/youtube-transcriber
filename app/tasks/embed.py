import uuid

import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models.channel import Channel
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

logger = structlog.get_logger()
sync_engine = create_engine(settings.database_url_sync)

SIDE_EFFECT_BEST_EFFORT = "best_effort_side_effect"
SIDE_EFFECT_BUG_MASK = "bug_mask_candidate"


def _speakers_count(transcription: Transcription | None) -> int | None:
    if transcription and getattr(transcription, "speakers", None):
        try:
            return len(transcription.speakers)
        except TypeError:
            return None
    return None


def _completion_payload(db: Session, video: Video, transcription: Transcription | None) -> dict[str, str | int | float | None]:
    channel_name = None
    if video.channel_id:
        channel = db.get(Channel, video.channel_id)
        channel_name = channel.name if channel else None
    return {
        "video_id": str(video.id),
        "channel_id": str(video.channel_id) if video.channel_id else None,
        "channel_name": channel_name,
        "title": video.title,
        "duration": video.duration_seconds,
        "speakers": _speakers_count(transcription),
    }


def _notify_completion(db: Session, video: Video, transcription: Transcription | None) -> None:
    """Send the best available completion notification.

    Report generation/delivery is intentionally non-fatal. If it is disabled or
    fails, the original short completion notification remains the fallback.
    """
    from app.services.telegram_notify import notify as _tg_notify

    payload = _completion_payload(db, video, transcription)
    video_id = str(video.id)
    channel_id = str(video.channel_id) if video.channel_id else None

    if settings.report_generation_enabled and settings.report_delivery_enabled:
        report_path = None
        try:
            from app.services.reporting import generate_video_report

            report = generate_video_report(db, video.id)
            report_path = report.artifact_path
            sent = _tg_notify(
                "video.report_ready",
                {
                    **payload,
                    "report_path": report.artifact_path,
                    "filename": report.artifact_path.rsplit("/", 1)[-1],
                    "summary": report.markdown_content,
                },
            )
            report.delivery_status = "sent" if sent else "failed"
            if not sent:
                report.delivery_error = "telegram_notify_returned_false"
                logger.warning(
                    "video_report_delivery_failed",
                    boundary="embed.report_generation_delivery",
                    category=SIDE_EFFECT_BEST_EFFORT,
                    event_type="video.report_ready",
                    video_id=video_id,
                    channel_id=channel_id,
                    report_path=report_path,
                    exception_type=None,
                    error_message="telegram_notify_returned_false",
                    outcome="fallback_sent",
                )
            db.commit()
            if sent:
                return
        except Exception as exc:  # noqa: BLE001 — report delivery must not fail pipeline completion
            logger.warning(
                "video_report_side_effect_failed",
                boundary="embed.report_generation_delivery",
                category=SIDE_EFFECT_BEST_EFFORT,
                event_type="video.report_ready",
                video_id=video_id,
                channel_id=channel_id,
                report_path=report_path,
                exception_type=exc.__class__.__name__,
                error_message=str(exc)[:1000],
                outcome="fallback_sent",
            )
            try:
                from app.models.video_report import VideoReport

                report = db.query(VideoReport).filter(VideoReport.video_id == video.id).first()
                if report:
                    report.delivery_status = "failed"
                    report.delivery_error = str(exc)[:1000]
                    db.commit()
            except Exception as state_exc:  # noqa: BLE001
                db.rollback()
                logger.warning(
                    "video_report_failure_state_update_failed",
                    boundary="embed.report_failure_state_update",
                    category=SIDE_EFFECT_BUG_MASK,
                    event_type="video.report_ready",
                    video_id=video_id,
                    channel_id=channel_id,
                    report_path=report_path,
                    exception_type=state_exc.__class__.__name__,
                    error_message=str(state_exc)[:1000],
                    outcome="caller_continued",
                )

    try:
        _tg_notify("video.completed", payload)
    except Exception as exc:  # noqa: BLE001 — completion notification must not fail caller
        logger.warning(
            "video_completion_notification_failed",
            boundary="embed.completion_notification",
            category=SIDE_EFFECT_BEST_EFFORT,
            event_type="video.completed",
            video_id=video_id,
            channel_id=channel_id,
            exception_type=exc.__class__.__name__,
            error_message=str(exc)[:1000],
            outcome="caller_continued",
        )


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
                _notify_completion(db, video, transcription)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "video_completion_side_effect_failed",
                    boundary="embed.completion_notification",
                    category=SIDE_EFFECT_BUG_MASK,
                    event_type="video.completed",
                    video_id=str(video.id),
                    job_id=str(job.id) if job else None,
                    channel_id=str(video.channel_id) if video.channel_id else None,
                    exception_type=exc.__class__.__name__,
                    error_message=str(exc)[:1000],
                    outcome="caller_continued",
                )

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
