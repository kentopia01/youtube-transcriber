from celery import chain, signature

from app.tasks.celery_app import celery

# Ordered list of pipeline steps
PIPELINE_STEPS = [
    "tasks.download_audio",
    "tasks.transcribe_audio",
    "tasks.diarize_and_align",
    "tasks.cleanup_transcript",
    "tasks.summarize_transcription",
    "tasks.generate_embeddings",
]


def run_pipeline(video_id: str) -> str:
    """Launch the full processing pipeline for a video.

    Pipeline: download → transcribe → diarize → cleanup → summarize → embed

    Diarization step is a no-op if DIARIZATION_ENABLED=false.
    Cleanup step is a no-op if TRANSCRIPT_CLEANUP_ENABLED=false.

    Uses task signatures by name to avoid importing worker-only dependencies
    in the web process.

    Returns the Celery chain AsyncResult ID.
    """
    return run_pipeline_from(video_id, start_from="tasks.download_audio")


def run_pipeline_from(video_id: str, start_from: str) -> str:
    """Launch a partial pipeline starting from the given step.

    Used by smart retry to skip steps whose output already exists.
    The first step in the partial chain receives video_id as an argument;
    subsequent steps receive it from the previous step via chaining.

    Returns the Celery chain AsyncResult ID.
    """
    if start_from not in PIPELINE_STEPS:
        raise ValueError(f"Unknown pipeline step: {start_from}")

    start_idx = PIPELINE_STEPS.index(start_from)
    steps = PIPELINE_STEPS[start_idx:]

    sigs = []
    for i, step_name in enumerate(steps):
        if i == 0:
            sigs.append(signature(step_name, args=[video_id], app=celery))
        else:
            sigs.append(signature(step_name, app=celery))

    pipeline = chain(*sigs)
    result = pipeline.apply_async()
    return result.id
