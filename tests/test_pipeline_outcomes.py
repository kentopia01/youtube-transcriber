from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid

from app.models.job import Job
from app.services import pipeline_outcomes as mod
from app.services.pipeline_observability import ATTEMPT_REASON_AUTO_INGEST


class _Query:
    def __init__(self, jobs):
        self.jobs = jobs

    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def all(self):
        return self.jobs


class _Db:
    def __init__(self, jobs):
        self.jobs = jobs

    def query(self, model):
        assert model is Job
        return _Query(self.jobs)


def _job(status: str, now: datetime) -> Job:
    return Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        job_type="pipeline",
        status=status,
        current_stage="download",
        attempt_creation_reason=ATTEMPT_REASON_AUTO_INGEST,
        created_at=now - timedelta(minutes=10),
    )


def test_outcome_watchdog_flags_failure_cluster_and_overdue(monkeypatch):
    now = datetime(2026, 8, 6, tzinfo=UTC)
    completed = _job("completed", now)
    failed_a = _job("failed", now)
    failed_b = _job("failed", now)
    overdue = _job("running", now)
    monkeypatch.setattr(mod, "is_pipeline_job_stale", lambda job, now=None: job is overdue)

    summary = mod.collect_pipeline_outcomes(
        _Db([completed, failed_a, failed_b, overdue]),
        now=now,
        failure_threshold=2,
    )

    assert summary.total == 4
    assert summary.completed == 1
    assert summary.failed == 2
    assert summary.active == 1
    assert summary.overdue == 1
    assert summary.degraded is True


def test_outcome_watchdog_stays_green_for_progressing_work(monkeypatch):
    now = datetime(2026, 8, 6, tzinfo=UTC)
    completed = _job("completed", now)
    active = _job("running", now)
    monkeypatch.setattr(mod, "is_pipeline_job_stale", lambda job, now=None: False)

    summary = mod.collect_pipeline_outcomes(
        _Db([completed, active]), now=now, failure_threshold=2
    )

    assert summary.degraded is False
    assert summary.active == 1
    assert summary.overdue == 0
