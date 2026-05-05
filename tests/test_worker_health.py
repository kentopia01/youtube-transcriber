from datetime import UTC, datetime, timedelta

from app.models.job import Job
from app.services.worker_health import (
    POST_PROGRESS_WINDOW_MINUTES,
    any_busy_healthy_jobs,
    job_is_busy_but_healthy,
    recent_post_log_progress_at,
)


def test_job_is_busy_but_healthy_for_recent_long_running_diarize_stage():
    now = datetime.now(UTC)
    job = Job(job_type="pipeline", status="running")
    job.current_stage = "diarize"
    job.current_stage_started_at = now - timedelta(minutes=10)
    job.last_activity_at = now - timedelta(minutes=10)

    assert job_is_busy_but_healthy(job, now=now) is True


def test_job_is_busy_but_healthy_for_recent_cleanup_stage_when_post_worker_busy():
    now = datetime.now(UTC)
    job = Job(job_type="pipeline", status="running")
    job.current_stage = "cleanup"
    job.current_stage_started_at = now - timedelta(minutes=10)
    job.last_activity_at = now - timedelta(minutes=10)

    assert job_is_busy_but_healthy(job, now=now) is True


def test_job_is_not_busy_healthy_when_long_running_stage_is_stale():
    now = datetime.now(UTC)
    job = Job(job_type="pipeline", status="running")
    job.current_stage = "diarize"
    job.current_stage_started_at = now - timedelta(hours=7)
    job.last_activity_at = now - timedelta(hours=7)

    assert job_is_busy_but_healthy(job, now=now) is False


def test_recent_cleanup_stage_becomes_unhealthy_after_stage_timeout():
    now = datetime.now(UTC)
    job = Job(job_type="pipeline", status="running")
    job.current_stage = "cleanup"
    job.current_stage_started_at = now - timedelta(hours=2)
    job.last_activity_at = now - timedelta(hours=2)

    assert job_is_busy_but_healthy(job, now=now) is False


def test_any_busy_healthy_jobs_detects_one_recent_long_running_job():
    now = datetime.now(UTC)
    busy = Job(job_type="pipeline", status="running")
    busy.current_stage = "transcribe"
    busy.current_stage_started_at = now - timedelta(minutes=5)
    busy.last_activity_at = now - timedelta(minutes=5)

    queued = Job(job_type="pipeline", status="queued")
    queued.current_stage = "queued"

    assert any_busy_healthy_jobs([queued, busy], now=now) is True


def test_post_cleanup_job_with_recent_db_activity_is_busy_healthy():
    now = datetime.now(UTC)
    job = Job(job_type="pipeline", status="running")
    job.current_stage = "cleanup"
    job.current_stage_started_at = now - timedelta(minutes=20)
    job.last_activity_at = now - timedelta(minutes=3)

    assert job_is_busy_but_healthy(job, now=now) is True


def test_post_cleanup_job_with_recent_log_progress_is_busy_healthy():
    now = datetime.now(UTC)
    job = Job(job_type="pipeline", status="running")
    job.current_stage = "summarize"
    job.current_stage_started_at = now - timedelta(minutes=30)
    job.last_activity_at = now - timedelta(minutes=POST_PROGRESS_WINDOW_MINUTES + 5)

    assert job_is_busy_but_healthy(
        job,
        now=now,
        post_log_progress_at=now - timedelta(minutes=2),
    ) is True


def test_post_cleanup_job_without_recent_progress_is_not_busy_healthy():
    now = datetime.now(UTC)
    job = Job(job_type="pipeline", status="running")
    job.current_stage = "cleanup"
    job.current_stage_started_at = now - timedelta(minutes=40)
    job.last_activity_at = now - timedelta(minutes=POST_PROGRESS_WINDOW_MINUTES + 10)

    assert job_is_busy_but_healthy(job, now=now) is False


def test_recent_post_log_progress_requires_progress_marker(tmp_path):
    log_path = tmp_path / "post.log"
    log_path.write_text("tasks.cleanup_transcript succeeded in 1.23s\n")

    assert recent_post_log_progress_at(log_path) is not None

    quiet_log = tmp_path / "quiet.log"
    quiet_log.write_text("worker booted\n")
    assert recent_post_log_progress_at(quiet_log) is None
