from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_db
from app.main import create_app
from app.models.job import Job
from app.services.operations_dashboard import (
    QueueCoverage,
    build_operations_summary,
    classify_batch_warning,
    derive_queue_health,
    load_channel_video_counts,
)


REQUIRED = frozenset({"audio", "diarize", "post", "celery"})


class _Scalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _Result:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return _Scalars(self.values)

    def all(self):
        return self.values


class _SummaryDB:
    def __init__(self, scalar_values, execute_values):
        self.scalar_values = list(scalar_values)
        self.execute_values = list(execute_values)
        self.scalar_statements = []
        self.execute_statements = []

    async def scalar(self, statement):
        self.scalar_statements.append(statement)
        return self.scalar_values.pop(0)

    async def execute(self, statement):
        self.execute_statements.append(statement)
        return _Result(self.execute_values.pop(0))


def _coverage(*queues: str, workers=("worker-1",), error_code=None):
    return QueueCoverage(
        workers=workers,
        covered_queues=frozenset(queues),
        required_queues=REQUIRED,
        error_code=error_code,
    )


def _job(status: str, *, stage: str = "queued", minutes_ago: int = 1) -> Job:
    now = datetime.now(UTC)
    job = Job(job_type="pipeline", status=status, hidden_from_queue=False)
    job.current_stage = stage
    job.created_at = now - timedelta(minutes=minutes_ago)
    job.current_stage_started_at = now - timedelta(minutes=minutes_ago)
    job.last_activity_at = now - timedelta(minutes=minutes_ago)
    return job


def test_queue_health_reports_idle_when_covered_without_work():
    health = derive_queue_health(_coverage(*REQUIRED), [])
    assert health.state == "idle"
    assert health.label == "Queue Idle"


def test_queue_health_reports_healthy_when_work_is_waiting():
    health = derive_queue_health(_coverage(*REQUIRED), [_job("queued")])
    assert health.state == "healthy"
    assert health.busy is False


def test_queue_health_reports_busy_when_work_is_running():
    health = derive_queue_health(
        _coverage(*REQUIRED),
        [_job("running", stage="transcribe")],
    )
    assert health.state == "busy"
    assert health.busy is True


def test_queue_health_reports_degraded_busy_without_complete_coverage():
    health = derive_queue_health(
        _coverage("audio", workers=("audio-worker",)),
        [_job("running", stage="transcribe")],
    )
    assert health.state == "degraded"
    assert health.busy is True
    assert health.missing_queues == ("celery", "diarize", "post")
    assert "recent progress" in health.detail


def test_queue_health_reports_unavailable_when_inspection_fails():
    health = derive_queue_health(
        _coverage(workers=(), error_code="TimeoutError"),
        [],
    )
    assert health.state == "unavailable"
    assert health.error_code == "TimeoutError"


def test_active_batch_with_terminal_children_is_explicitly_stale():
    batch = SimpleNamespace(
        id=uuid.uuid4(),
        status="running",
        created_at=datetime.now(UTC) - timedelta(minutes=5),
        jobs=[_job("completed"), _job("failed")],
    )
    warning = classify_batch_warning(batch)
    assert warning is not None
    assert warning.reason == "terminal_jobs_unreconciled"


@pytest.mark.asyncio
async def test_summary_returns_true_counts_above_display_limits_and_warnings():
    db = _SummaryDB(
        scalar_values=[40, 31, 8, 12, 7, 4, 9, 2, 3],
        execute_values=[[], []],
    )

    summary = await build_operations_summary(
        db,
        now=datetime(2026, 7, 21, tzinfo=UTC),
        queue_probe=lambda: _coverage(*REQUIRED),
    )

    assert summary.counts.active_jobs == 12
    assert summary.counts.pending_jobs == 7
    assert summary.counts.in_flight_jobs == 19
    assert summary.counts.failed_visible_jobs == 4
    assert summary.counts.report_delivery_warnings == 2
    assert summary.counts.subscription_warnings == 3
    assert summary.warning_count == 9
    assert summary.queue_health.state == "idle"


@pytest.mark.asyncio
async def test_channel_video_counts_use_linked_videos_not_cached_channel_counter():
    first_channel = uuid.uuid4()
    second_channel = uuid.uuid4()
    db = _SummaryDB(
        scalar_values=[],
        execute_values=[[(first_channel, 7), (second_channel, 0)]],
    )

    counts = await load_channel_video_counts(db)

    assert counts == {first_channel: 7, second_channel: 0}


def test_operations_summary_route_exposes_structured_contract():
    db = _SummaryDB(
        scalar_values=[40, 31, 8, 12, 7, 4, 9, 2, 3],
        execute_values=[[], []],
    )
    app = create_app()
    app.state.operations_queue_probe = lambda: _coverage(*REQUIRED)

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    response = TestClient(app).get("/api/operations/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["active_jobs"] == 12
    assert body["counts"]["in_flight_jobs"] == 19
    assert body["counts"]["report_delivery_warnings"] == 2
    assert body["queue_health"]["state"] == "idle"
