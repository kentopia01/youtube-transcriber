"""Tests for scripts/reap_hidden_superseded_failed_jobs.py."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "reap_hidden_superseded_failed_jobs.py"
)
spec = importlib.util.spec_from_file_location(
    "reap_hidden_superseded_failed_jobs", _SCRIPT_PATH
)
mod = importlib.util.module_from_spec(spec)
sys.modules["reap_hidden_superseded_failed_jobs"] = mod
spec.loader.exec_module(mod)


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed: list[tuple[str, tuple | None]] = []

    def execute(self, query, params=None):
        normalized = " ".join(str(query).split())
        self.executed.append((normalized, params))

    def fetchall(self):
        return self.rows


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.autocommit = False
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


def test_dry_run_only_reports_hidden_superseded_failed_jobs(monkeypatch):
    old_hidden_at = datetime.now(timezone.utc) - timedelta(days=30)
    rows = [
        (uuid.uuid4(), uuid.uuid4(), old_hidden_at, uuid.uuid4()),
    ]
    cursor = _FakeCursor(rows)
    conn = _FakeConn(cursor)

    monkeypatch.setattr(mod.psycopg2, "connect", lambda _: conn)

    count = mod.reap_hidden_superseded_failed_jobs(
        db_url="postgresql://example",
        retention_days=14,
        dry_run=True,
    )

    assert count == 1
    assert conn.closed is True
    assert len(cursor.executed) == 1

    select_sql, params = cursor.executed[0]
    assert "FROM jobs" in select_sql
    assert "status = 'failed'" in select_sql
    assert "hidden_from_queue = TRUE" in select_sql
    assert "hidden_reason = 'superseded'" in select_sql
    assert "superseded_by_job_id IS NOT NULL" in select_sql
    assert params is not None


def test_non_dry_run_deletes_only_selected_hidden_superseded_failed_jobs(monkeypatch):
    rows = [
        (uuid.uuid4(), uuid.uuid4(), datetime.now(timezone.utc) - timedelta(days=20), uuid.uuid4()),
        (uuid.uuid4(), uuid.uuid4(), datetime.now(timezone.utc) - timedelta(days=16), uuid.uuid4()),
    ]
    cursor = _FakeCursor(rows)
    conn = _FakeConn(cursor)

    monkeypatch.setattr(mod.psycopg2, "connect", lambda _: conn)

    count = mod.reap_hidden_superseded_failed_jobs(
        db_url="postgresql://example",
        retention_days=14,
        dry_run=False,
    )

    assert count == 2

    delete_statements = [entry for entry in cursor.executed if entry[0].startswith("DELETE FROM jobs")]
    assert len(delete_statements) == 2
    deleted_ids = {stmt[1][0] for stmt in delete_statements}
    assert deleted_ids == {rows[0][0], rows[1][0]}


def test_main_returns_zero_when_matching_jobs_are_found(monkeypatch):
    called = {}

    def _fake_reap(*, db_url, retention_days, dry_run):
        called.update(
            db_url=db_url,
            retention_days=retention_days,
            dry_run=dry_run,
        )
        return 3

    monkeypatch.setattr(mod, "reap_hidden_superseded_failed_jobs", _fake_reap)

    exit_code = mod.main([
        "--db-url",
        "postgresql://example",
        "--retention-days",
        "14",
        "--dry-run",
    ])

    assert exit_code == 0
    assert called == {
        "db_url": "postgresql://example",
        "retention_days": 14,
        "dry_run": True,
    }
