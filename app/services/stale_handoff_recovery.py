"""Bounded same-attempt recovery for stale Celery stage handoffs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.models.job import Job
from app.models.video import Video
from app.services.pipeline_enqueue import enqueue_pipeline_job_after_commit
from app.services.pipeline_resume import detect_resume_point_sync
from app.services.pipeline_state import set_pipeline_job_state
from app.tasks.pipeline import run_pipeline_from

_TASK_STAGE = {
    "tasks.download_audio": "download",
    "tasks.transcribe_audio": "transcribe",
    "tasks.diarize_and_align": "diarize",
    "tasks.cleanup_transcript": "cleanup",
    "tasks.summarize_transcription": "summarize",
    "tasks.generate_embeddings": "embed",
}
_STAGE_INDEX = {
    "queued": -1,
    "download": 0,
    "transcribe": 1,
    "diarize": 2,
    "cleanup": 3,
    "summarize": 4,
    "embed": 5,
}
_RECOVERY_COUNT_KEY = "stale_handoff_recovery_count"


@dataclass(slots=True)
class StaleHandoffPlan:
    recover: bool
    reason: str
    start_from: str | None = None
    artifact_check_result: dict[str, Any] | None = None
    recovery_count: int = 0


def plan_stale_handoff_recovery(
    db: Session,
    job: Job,
    video: Video | None,
) -> StaleHandoffPlan:
    metadata = dict(job.last_artifact_check_result or {})
    recovery_count = int(metadata.get(_RECOVERY_COUNT_KEY) or 0)
    if recovery_count >= settings.pipeline_stale_handoff_recovery_limit:
        return StaleHandoffPlan(False, "recovery_limit_reached", recovery_count=recovery_count)
    if video is None:
        return StaleHandoffPlan(False, "missing_video", recovery_count=recovery_count)

    start_from, artifact_result = detect_resume_point_sync(db, video)
    target_stage = _TASK_STAGE.get(start_from)
    current_stage = job.current_stage or "queued"
    if target_stage is None:
        return StaleHandoffPlan(False, "unknown_resume_stage", recovery_count=recovery_count)

    current_index = _STAGE_INDEX.get(current_stage, -1)
    target_index = _STAGE_INDEX[target_stage]
    has_forward_artifact = target_index > current_index
    completed_embed_handoff = (
        current_stage == "embed"
        and target_stage == "embed"
        and bool(artifact_result.get("has_embeddings"))
    )
    if not has_forward_artifact and not completed_embed_handoff:
        return StaleHandoffPlan(
            False,
            "no_forward_artifact_progress",
            start_from=start_from,
            artifact_check_result=artifact_result,
            recovery_count=recovery_count,
        )

    merged = dict(metadata)
    merged.update(artifact_result)
    merged[_RECOVERY_COUNT_KEY] = recovery_count + 1
    merged["stale_handoff_recovery_reason"] = (
        f"stale_{current_stage}_resume_{target_stage}"
    )
    return StaleHandoffPlan(
        True,
        "forward_artifact_progress",
        start_from=start_from,
        artifact_check_result=merged,
        recovery_count=recovery_count + 1,
    )


def recover_stale_handoff(
    db: Session,
    job: Job,
    video: Video | None,
    *,
    publish: Callable[[], str] | None = None,
) -> StaleHandoffPlan:
    plan = plan_stale_handoff_recovery(db, job, video)
    if not plan.recover or plan.start_from is None or video is None:
        return plan

    job.last_artifact_check_result = plan.artifact_check_result
    start_label = plan.start_from.split(".")[-1]
    set_pipeline_job_state(
        job,
        lifecycle_status="queued",
        progress_message=f"Recovered stale stage handoff; resuming from {start_label}",
        error_message=None,
        worker_hostname=None,
        worker_task_id=None,
    )
    video.status = "pending"
    video.error_message = None
    video_id = str(video.id)
    job_id = str(job.id)
    enqueue_pipeline_job_after_commit(
        db,
        job,
        publish=publish
        or (lambda: run_pipeline_from(video_id, start_from=plan.start_from, job_id=job_id)),
    )
    return plan
