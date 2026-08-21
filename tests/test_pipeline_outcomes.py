from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid

from app.models.job import Job
from app.models.video import Video
from app.services.pipeline_outcome_alerts import (
    ALERT_STATE_VERSION,
    decide_pipeline_outcome_alert,
    load_pipeline_outcome_alert_state,
    save_pipeline_outcome_alert_state,
)
from app.services import pipeline_outcomes as mod
from app.services.pipeline_observability import (
    ATTEMPT_REASON_AUTO_INGEST,
    ATTEMPT_REASON_USER_RETRY,
)
from scripts import check_pipeline_outcomes as outcome_command


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


def _job(
    status: str,
    now: datetime,
    *,
    youtube_id: str | None = None,
    video_id: uuid.UUID | None = None,
    attempt_number: int = 1,
    reason: str = ATTEMPT_REASON_AUTO_INGEST,
    minutes_ago: int = 10,
) -> Job:
    job = Job(
        id=uuid.uuid4(),
        video_id=video_id or uuid.uuid4(),
        job_type="pipeline",
        status=status,
        current_stage="download",
        attempt_number=attempt_number,
        attempt_creation_reason=reason,
        created_at=now - timedelta(minutes=minutes_ago),
    )
    if youtube_id:
        job.video = Video(
            id=job.video_id,
            youtube_video_id=youtube_id,
            title=f"Video {youtube_id}",
            url=f"https://youtube.com/watch?v={youtube_id}",
        )
    return job


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
    assert len(summary.failed_jobs) == 2
    assert summary.failed_jobs[0].stage == "download"


def test_outcome_watchdog_uses_latest_retry_even_when_original_is_hidden():
    now = datetime(2026, 8, 21, tzinfo=UTC)
    video_id = uuid.uuid4()
    original = _job(
        "failed",
        now,
        video_id=video_id,
        attempt_number=1,
        minutes_ago=20,
    )
    original.hidden_from_queue = True
    retry = _job(
        "failed",
        now,
        video_id=video_id,
        attempt_number=2,
        reason=ATTEMPT_REASON_USER_RETRY,
        minutes_ago=5,
    )

    summary = mod.collect_pipeline_outcomes(
        _Db([original, retry]),
        now=now,
        failure_threshold=1,
    )

    assert summary.total == 1
    assert summary.failed == 1
    assert summary.completed == 0
    assert summary.failed_job_ids == [str(retry.id)]
    assert summary.failed_jobs[0].attempt_number == 2


def test_outcome_watchdog_recovers_only_when_latest_retry_completed():
    now = datetime(2026, 8, 21, tzinfo=UTC)
    video_id = uuid.uuid4()
    original = _job(
        "failed",
        now,
        video_id=video_id,
        attempt_number=1,
        minutes_ago=20,
    )
    original.hidden_from_queue = True
    retry = _job(
        "completed",
        now,
        video_id=video_id,
        attempt_number=2,
        reason=ATTEMPT_REASON_USER_RETRY,
        minutes_ago=5,
    )
    unrelated_manual = _job(
        "failed",
        now,
        reason=ATTEMPT_REASON_USER_RETRY,
        minutes_ago=2,
    )

    summary = mod.collect_pipeline_outcomes(
        _Db([original, retry, unrelated_manual]),
        now=now,
        failure_threshold=1,
    )

    assert summary.total == 1
    assert summary.completed == 1
    assert summary.failed == 0
    assert summary.degraded is False


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


def _degraded_summary(now: datetime, *, youtube_id: str = "abc123"):
    failed_a = _job("failed", now, youtube_id=youtube_id)
    failed_a.error_message = "The page needs to be reloaded\n before continuing"
    failed_b = _job("failed", now, youtube_id="def456")
    failed_b.attempt_number = 2
    return mod.collect_pipeline_outcomes(
        _Db([failed_a, failed_b]), now=now, failure_threshold=2
    )


def test_actionable_alert_is_sent_for_new_incident_and_suppresses_unchanged_repeat():
    now = datetime(2026, 8, 21, tzinfo=UTC)
    summary = _degraded_summary(now)

    first = decide_pipeline_outcome_alert(summary, now=now)
    repeated = decide_pipeline_outcome_alert(
        summary,
        first.next_state,
        now=now + timedelta(minutes=30),
    )

    assert first.kind == "new"
    assert "Last 24h: 2 videos" in first.message
    assert "Affected latest outcomes:" in first.message
    assert "Video abc123 [abc123]" in first.message
    assert "failed at download; no retry yet" in first.message
    assert "retry attempt 2" in first.message
    assert "The page needs to be reloaded before continuing" in first.message
    assert repeated.kind == "suppressed"
    assert repeated.message is None
    assert summary.degraded is True


def test_actionable_alert_reports_changed_incident_and_periodic_reminder():
    now = datetime(2026, 8, 21, tzinfo=UTC)
    original = _degraded_summary(now)
    first = decide_pipeline_outcome_alert(original, now=now)
    changed = _degraded_summary(now, youtube_id="new789")

    changed_decision = decide_pipeline_outcome_alert(
        changed,
        first.next_state,
        now=now + timedelta(minutes=30),
    )
    reminder = decide_pipeline_outcome_alert(
        changed,
        changed_decision.next_state,
        now=now + timedelta(hours=3),
    )

    assert changed_decision.kind == "changed"
    assert "Incident changed" in changed_decision.message
    assert "new789" in changed_decision.message
    assert reminder.kind == "reminder"
    assert "Still degraded" in reminder.message


def test_actionable_alert_sends_one_recovery_transition(monkeypatch):
    now = datetime(2026, 8, 21, tzinfo=UTC)
    degraded = _degraded_summary(now)
    first = decide_pipeline_outcome_alert(degraded, now=now)
    completed = _job("completed", now)
    monkeypatch.setattr(mod, "is_pipeline_job_stale", lambda job, now=None: False)
    healthy = mod.collect_pipeline_outcomes(
        _Db([completed]), now=now + timedelta(hours=1), failure_threshold=2
    )

    recovered = decide_pipeline_outcome_alert(
        healthy,
        first.next_state,
        now=now + timedelta(hours=1),
    )
    stable = decide_pipeline_outcome_alert(
        healthy,
        recovered.next_state,
        now=now + timedelta(hours=2),
    )

    assert recovered.kind == "recovered"
    assert "watchdog recovered" in recovered.message
    assert "after 1h 0m" in recovered.message
    assert stable.kind == "healthy"
    assert stable.message is None


def test_pipeline_outcome_alert_state_round_trip(tmp_path):
    state_path = tmp_path / "nested" / "alert.json"
    state = {
        "version": ALERT_STATE_VERSION,
        "degraded": True,
        "fingerprint": "example",
    }

    save_pipeline_outcome_alert_state(state_path, state)

    assert load_pipeline_outcome_alert_state(state_path) == state
    assert state_path.stat().st_mode & 0o777 == 0o600


def test_alert_output_treats_degraded_state_as_successful_observation():
    assert outcome_command.process_exit_code(degraded=True, alert_output=True) == 0


def test_operator_health_mode_preserves_nonzero_degraded_exit():
    assert outcome_command.process_exit_code(degraded=True, alert_output=False) == 1
    assert outcome_command.process_exit_code(degraded=False, alert_output=False) == 0
