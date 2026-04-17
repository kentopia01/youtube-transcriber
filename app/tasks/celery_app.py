from celery import Celery

from app.config import settings
from app.services.pipeline_routing import PIPELINE_TASK_STAGE_MAP, get_queue_for_task

celery = Celery(
    "youtube_transcriber",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

celery.conf.update(
    include=[
        "app.tasks.download",
        "app.tasks.transcribe",
        "app.tasks.diarize",
        "app.tasks.cleanup",
        "app.tasks.summarize",
        "app.tasks.embed",
        "app.tasks.channel_sync",
        "app.tasks.generate_persona",
        "app.tasks.weekly_digest",
        "app.tasks.poll_subscriptions",
        "app.tasks.compress_stale_videos",
    ],
    task_routes={
        task_name: {"queue": get_queue_for_task(task_name)}
        for task_name in PIPELINE_TASK_STAGE_MAP
    },
)
