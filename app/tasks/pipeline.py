from celery import chain, signature

from app.config import settings
from app.services.pipeline_routing import get_queue_for_task
from app.tasks.celery_app import celery
from app.tasks.helpers import build_pipeline_task_payload

# Ordered list of all pipeline tasks.
DIARIZATION_TASK = "tasks.diarize_and_align"
PIPELINE_TASKS = [
    "tasks.download_audio",
    "tasks.transcribe_audio",
    DIARIZATION_TASK,
    "tasks.cleanup_transcript",
    "tasks.summarize_transcription",
    "tasks.generate_embeddings",
]


def _selected_pipeline_tasks() -> list[str]:
    if settings.inline_diarization_enabled:
        return list(PIPELINE_TASKS)
    return [task_name for task_name in PIPELINE_TASKS if task_name != DIARIZATION_TASK]


def _stage_signature(task_name: str, payload: dict[str, str], *, immutable: bool = False):
    return signature(task_name, args=[payload], app=celery, immutable=immutable).set(
        queue=get_queue_for_task(task_name)
    )


def run_pipeline(video_id: str, job_id: str | None = None) -> str:
    payload = build_pipeline_task_payload(video_id, job_id or "")
    selected_tasks = _selected_pipeline_tasks()
    sigs = [
        _stage_signature(task_name, payload, immutable=index > 0)
        for index, task_name in enumerate(selected_tasks)
    ]
    result = chain(*sigs).apply_async()
    return result.id


def run_pipeline_from(video_id: str, start_from: str, job_id: str | None = None) -> str:
    if start_from not in PIPELINE_TASKS:
        raise ValueError(f"Unknown start task: {start_from}")

    payload = build_pipeline_task_payload(video_id, job_id or "")
    selected_tasks = _selected_pipeline_tasks()
    if start_from in selected_tasks:
        start_index = selected_tasks.index(start_from)
        remaining_tasks = selected_tasks[start_index:]
    else:
        start_index = PIPELINE_TASKS.index(start_from)
        remaining_tasks = PIPELINE_TASKS[start_index:]
    sigs = [
        _stage_signature(task_name, payload, immutable=index > 0)
        for index, task_name in enumerate(remaining_tasks)
    ]
    result = chain(*sigs).apply_async()
    return result.id
