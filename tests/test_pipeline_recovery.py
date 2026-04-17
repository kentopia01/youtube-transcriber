from datetime import UTC, datetime, timedelta

from app.models.job import Job
from app.services import pipeline_recovery
from app.services.pipeline_recovery import (
    MANUAL_REVIEW_RECOVERY_STATUS,
    build_failure_signature,
    get_retry_block_reason,
    get_stage_stale_timeout_minutes,
    is_pipeline_job_stale,
    record_pipeline_failure,
)


def test_build_failure_signature_normalizes_numbers_and_paths():
    signature = build_failure_signature(
        "transcribe",
        RuntimeError("Decoder failed for /tmp/audio/123.wav after 456 seconds"),
    )

    assert signature.startswith("transcribe|RuntimeError|")
    assert "<path>" in signature
    assert "123" not in signature
    assert "456" not in signature


def test_is_pipeline_job_stale_respects_stage_specific_timeout():
    now = datetime.now(UTC)
    job = Job(job_type="pipeline", status="running")
    job.current_stage = "transcribe"
    job.last_activity_at = now - timedelta(minutes=get_stage_stale_timeout_minutes("transcribe") - 5)

    assert is_pipeline_job_stale(job, now=now) is False

    job.last_activity_at = now - timedelta(minutes=get_stage_stale_timeout_minutes("transcribe") + 5)
    assert is_pipeline_job_stale(job, now=now) is True


def test_is_pipeline_job_stale_prefers_recent_activity_over_old_stage_timestamp():
    now = datetime.now(UTC)
    job = Job(job_type="pipeline", status="running")
    job.current_stage = "transcribe"
    job.stage_updated_at = now - timedelta(minutes=get_stage_stale_timeout_minutes("transcribe") + 120)
    job.last_activity_at = now - timedelta(minutes=5)

    assert is_pipeline_job_stale(job, now=now) is False


def test_get_retry_block_reason_only_blocks_manual_review_jobs():
    job = Job(job_type="pipeline", status="failed")
    assert get_retry_block_reason(job) is None

    job.recovery_status = MANUAL_REVIEW_RECOVERY_STATUS
    job.recovery_reason = "Manual review required after repeated failures."
    assert get_retry_block_reason(job) == "Manual review required after repeated failures."


def test_record_pipeline_failure_sets_manual_review_after_repeated_identical_failures(monkeypatch):
    job = Job(job_type="pipeline", status="running")
    job.video_id = "video-1"
    video = type("VideoStub", (), {"status": "running", "error_message": None})()

    monkeypatch.setattr(pipeline_recovery, "count_prior_identical_failures", lambda db, job, signature: 1)

    message = record_pipeline_failure(
        db=object(),
        job=job,
        video=video,
        stage="transcribe",
        error=RuntimeError("decoder failed"),
        default_message="Transcription failed: decoder failed",
    )

    assert job.recovery_status == MANUAL_REVIEW_RECOVERY_STATUS
    assert job.failure_signature_count == 2
    assert job.manual_review_required is True
    assert "Manual review required" in message
    assert "Manual review required" in video.error_message
