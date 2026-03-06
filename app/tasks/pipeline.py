from celery import chain, signature

from app.tasks.celery_app import celery


def run_pipeline(video_id: str) -> str:
    """Launch the full processing pipeline for a video.

    Pipeline: download → transcribe → diarize → cleanup → summarize → embed

    Diarization step is a no-op if DIARIZATION_ENABLED=false.
    Cleanup step is a no-op if TRANSCRIPT_CLEANUP_ENABLED=false.

    Uses task signatures by name to avoid importing worker-only dependencies
    in the web process.

    Returns the Celery chain AsyncResult ID.
    """
    pipeline = chain(
        signature("tasks.download_audio", args=[video_id], app=celery),
        signature("tasks.transcribe_audio", app=celery),
        signature("tasks.diarize_and_align", app=celery),
        signature("tasks.cleanup_transcript", app=celery),
        signature("tasks.summarize_transcription", app=celery),
        signature("tasks.generate_embeddings", app=celery),
    )
    result = pipeline.apply_async()
    return result.id
