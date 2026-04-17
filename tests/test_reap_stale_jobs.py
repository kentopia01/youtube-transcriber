"""Tests for scripts/reap_stale_jobs.py."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.models.job import Job


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "reap_stale_jobs.py"
spec = importlib.util.spec_from_file_location("reap_stale_jobs", _SCRIPT_PATH)
mod = importlib.util.module_from_spec(spec)
sys.modules["reap_stale_jobs"] = mod
spec.loader.exec_module(mod)


class _FakeQuery:
    def __init__(self, jobs):
        self._jobs = jobs

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._jobs)


class _FakeDB:
    def __init__(self, jobs, videos=None):
        self.jobs = list(jobs)
        self.videos = videos or {}
        self.commit_calls = 0

    def query(self, model):
        assert model is mod.Job
        return _FakeQuery(self.jobs)

    def get(self, model, key):
        assert model is mod.Video
        return self.videos.get(key)

    def commit(self):
        self.commit_calls += 1


class _SessionFactory:
    def __init__(self, db):
        self._db = db

    def __call__(self, _engine):
        db = self._db

        class _Ctx:
            def __enter__(self):
                return db

            def __exit__(self, exc_type, exc, tb):
                return False

        return _Ctx()


def test_dry_run_reports_stale_jobs_without_marking_failures(monkeypatch):
    stale_job = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        job_type="pipeline",
        status="running",
        current_stage="transcribe",
    )
    active_job = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        job_type="pipeline",
        status="running",
        current_stage="download",
    )
    db = _FakeDB([stale_job, active_job])

    monkeypatch.setattr(mod, "Session", _SessionFactory(db))
    monkeypatch.setattr(mod, "is_pipeline_job_stale", lambda job, now=None: job.id == stale_job.id)

    recorded = []

    def _record(*args, **kwargs):
        recorded.append((args, kwargs))

    monkeypatch.setattr(mod, "record_pipeline_failure", _record)

    count = mod.reap_stale_jobs(dry_run=True)

    assert count == 0
    assert recorded == []
    assert db.commit_calls == 0


def test_non_dry_run_marks_only_stale_jobs_failed(monkeypatch):
    stale_job = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        job_type="pipeline",
        status="running",
        current_stage="summarize",
    )
    stale_job.last_activity_at = datetime.now(UTC) - timedelta(hours=3)
    db = _FakeDB([stale_job], videos={stale_job.video_id: object()})

    monkeypatch.setattr(mod, "Session", _SessionFactory(db))
    monkeypatch.setattr(mod, "is_pipeline_job_stale", lambda job, now=None: True)

    recorded = []

    def _record(db, job, *, video, stage, error, default_message, stale_reap):
        recorded.append(
            {
                "job_id": job.id,
                "video": video,
                "stage": stage,
                "error": str(error),
                "default_message": default_message,
                "stale_reap": stale_reap,
            }
        )

    monkeypatch.setattr(mod, "record_pipeline_failure", _record)

    count = mod.reap_stale_jobs(dry_run=False)

    assert count == 1
    assert db.commit_calls == 1
    assert len(recorded) == 1
    assert recorded[0]["job_id"] == stale_job.id
    assert recorded[0]["stage"] == "summarize"
    assert recorded[0]["stale_reap"] is True
    assert "Stale job reaped" in recorded[0]["error"]


def test_timeout_override_uses_activity_anchor_without_stage_classifier(monkeypatch):
    stale_job = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        job_type="pipeline",
        status="running",
        current_stage="transcribe",
    )
    stale_job.last_activity_at = datetime.now(UTC) - timedelta(hours=5)

    fresh_job = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        job_type="pipeline",
        status="running",
        current_stage="transcribe",
    )
    fresh_job.last_activity_at = datetime.now(UTC) - timedelta(minutes=20)

    db = _FakeDB([stale_job, fresh_job], videos={stale_job.video_id: object(), fresh_job.video_id: object()})

    monkeypatch.setattr(mod, "Session", _SessionFactory(db))
    monkeypatch.setattr(
        mod,
        "is_pipeline_job_stale",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    recorded = []

    def _record(*args, **kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(mod, "record_pipeline_failure", _record)

    count = mod.reap_stale_jobs(dry_run=False, timeout_hours=1.0)

    assert count == 1
    assert len(recorded) == 1
    assert db.commit_calls == 1
