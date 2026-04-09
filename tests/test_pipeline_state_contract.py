import uuid

from app.models.job import Job
from app.services.pipeline_state import (
    PIPELINE_STAGE_CANCELLED,
    PIPELINE_STAGE_COMPLETED,
    PIPELINE_STAGE_QUEUED,
    PIPELINE_STAGE_TRANSCRIBE,
    classify_pipeline_attempt,
    set_pipeline_job_state,
)


def test_classify_pipeline_attempt_buckets_active_terminal_and_superseded():
    active = Job(job_type="pipeline", status="running")
    terminal = Job(job_type="pipeline", status="failed")
    superseded = Job(job_type="pipeline", status="failed")
    superseded.hidden_reason = "superseded"
    superseded.superseded_by_job_id = uuid.uuid4()

    assert classify_pipeline_attempt(active) == "active"
    assert classify_pipeline_attempt(terminal) == "terminal"
    assert classify_pipeline_attempt(superseded) == "superseded"


def test_set_pipeline_job_state_tracks_lifecycle_and_current_stage():
    job = Job(job_type="pipeline", status="queued")

    set_pipeline_job_state(
        job,
        lifecycle_status="running",
        current_stage=PIPELINE_STAGE_TRANSCRIBE,
        progress_pct=30.0,
        progress_message="Transcribing audio...",
        completed_at=None,
    )

    assert job.status == "running"
    assert job.current_stage == PIPELINE_STAGE_TRANSCRIBE
    assert job.progress_pct == 30.0
    assert job.progress_message == "Transcribing audio..."
    assert job.started_at is not None
    assert job.stage_updated_at is not None
    assert job.completed_at is None
    assert job.attempt_state == "active"
    assert job.last_activity_at is not None

    set_pipeline_job_state(
        job,
        lifecycle_status="failed",
        error_message="boom",
    )

    assert job.status == "failed"
    assert job.current_stage == PIPELINE_STAGE_TRANSCRIBE
    assert job.error_message == "boom"
    assert job.completed_at is not None
    assert job.attempt_state == "terminal"


def test_set_pipeline_job_state_sets_queued_stage_for_active_queue_entries():
    job = Job(job_type="pipeline", status="pending")

    set_pipeline_job_state(
        job,
        lifecycle_status="queued",
        current_stage=PIPELINE_STAGE_QUEUED,
        progress_pct=0.0,
        progress_message="Queued for processing",
        started_at=None,
        completed_at=None,
        error_message=None,
    )

    assert job.status == "queued"
    assert job.current_stage == PIPELINE_STAGE_QUEUED
    assert job.progress_pct == 0.0
    assert job.error_message is None
    assert job.attempt_state == "active"


def test_set_pipeline_job_state_normalizes_queued_lifecycle_even_with_stale_stage_input():
    job = Job(job_type="pipeline", status="running")
    job.current_stage = PIPELINE_STAGE_TRANSCRIBE

    set_pipeline_job_state(
        job,
        lifecycle_status="queued",
        current_stage=PIPELINE_STAGE_TRANSCRIBE,
        progress_message="Moved back to queue",
        completed_at=None,
    )

    assert job.status == "queued"
    assert job.current_stage == PIPELINE_STAGE_QUEUED


def test_set_pipeline_job_state_running_lifecycle_clears_terminal_stage_when_not_provided():
    job = Job(job_type="pipeline", status="completed")
    job.current_stage = PIPELINE_STAGE_COMPLETED

    set_pipeline_job_state(
        job,
        lifecycle_status="running",
        progress_message="Resumed",
        completed_at=None,
    )

    assert job.status == "running"
    assert job.current_stage == PIPELINE_STAGE_QUEUED
    assert job.stage_updated_at is not None


def test_set_pipeline_job_state_auto_sets_terminal_stage_from_lifecycle():
    completed = Job(job_type="pipeline", status="running")
    completed.current_stage = PIPELINE_STAGE_TRANSCRIBE

    set_pipeline_job_state(
        completed,
        lifecycle_status="completed",
        progress_pct=100.0,
    )

    assert completed.status == "completed"
    assert completed.current_stage == PIPELINE_STAGE_COMPLETED
    assert completed.completed_at is not None

    cancelled = Job(job_type="pipeline", status="queued")

    set_pipeline_job_state(
        cancelled,
        lifecycle_status="cancelled",
        progress_message="Cancelled by user",
    )

    assert cancelled.status == "cancelled"
    assert cancelled.current_stage == PIPELINE_STAGE_CANCELLED


def test_manual_review_required_property_reflects_recovery_status():
    job = Job(job_type="pipeline", status="failed")
    assert job.manual_review_required is False

    job.recovery_status = "manual_review"
    assert job.manual_review_required is True


def test_set_pipeline_job_state_only_updates_stage_timestamp_on_stage_transition():
    job = Job(job_type="pipeline", status="queued")

    set_pipeline_job_state(
        job,
        lifecycle_status="running",
        current_stage=PIPELINE_STAGE_TRANSCRIBE,
        progress_pct=30.0,
    )
    first_stage_timestamp = job.stage_updated_at

    set_pipeline_job_state(
        job,
        lifecycle_status="running",
        current_stage=PIPELINE_STAGE_TRANSCRIBE,
        progress_pct=45.0,
    )

    assert job.stage_updated_at == first_stage_timestamp
