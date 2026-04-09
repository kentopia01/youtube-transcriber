from datetime import UTC, datetime, timedelta

from app.models.job import Job
from app.services.worker_health import any_busy_healthy_jobs, job_is_busy_but_healthy


def test_job_is_busy_but_healthy_for_recent_long_running_diarize_stage():
    now = datetime.now(UTC)
    job = Job(job_type="pipeline", status="running")
    job.current_stage = "diarize"
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


def test_any_busy_healthy_jobs_detects_one_recent_long_running_job():
    now = datetime.now(UTC)
    busy = Job(job_type="pipeline", status="running")
    busy.current_stage = "transcribe"
    busy.current_stage_started_at = now - timedelta(minutes=5)
    busy.last_activity_at = now - timedelta(minutes=5)

    queued = Job(job_type="pipeline", status="queued")
    queued.current_stage = "queued"

    assert any_busy_healthy_jobs([queued, busy], now=now) is True
