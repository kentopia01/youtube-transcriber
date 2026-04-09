#!/usr/bin/env python3
"""Reap truly stale pipeline jobs using stage-aware guardrails.

This Phase 3 version uses explicit pipeline stage/activity metadata instead of
legacy status names so slow but still-active work is not reaped too eagerly.

Usage:
  python scripts/reap_stale_jobs.py [--dry-run]
"""

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.models.job import Job
from app.models.video import Video
from app.services.pipeline_recovery import (
    get_job_activity_anchor,
    get_stage_stale_timeout_minutes,
    is_pipeline_job_stale,
    record_pipeline_failure,
)

def _resolve_db_url_sync() -> str:
    explicit = os.environ.get("DATABASE_URL_SYNC")
    if explicit:
        return explicit

    native_env = PROJECT_ROOT / ".env.native"
    if native_env.exists():
        for line in native_env.read_text().splitlines():
            if line.startswith("DATABASE_URL_SYNC="):
                return line.split("=", 1)[1].strip()

    return settings.database_url_sync


sync_engine = create_engine(_resolve_db_url_sync())


def reap_stale_jobs(dry_run: bool, timeout_hours: float | None = None):
    now = datetime.now(UTC)
    reaped = 0

    with Session(sync_engine) as db:
        candidates = (
            db.query(Job)
            .filter(Job.job_type == "pipeline", Job.status.in_(["pending", "queued", "running"]))
            .order_by(Job.created_at.asc())
            .all()
        )

        stale_jobs = []
        for job in candidates:
            if timeout_hours is not None:
                anchor = get_job_activity_anchor(job)
                if anchor is None:
                    continue
                if anchor.tzinfo is None:
                    anchor = anchor.replace(tzinfo=UTC)
                if now - anchor > timedelta(hours=timeout_hours):
                    stale_jobs.append(job)
                continue

            if is_pipeline_job_stale(job, now=now):
                stale_jobs.append(job)

        if not stale_jobs:
            print("No stale jobs found")
            return 0

        print(f"Found {len(stale_jobs)} stale job(s):")
        for job in stale_jobs:
            anchor = get_job_activity_anchor(job)
            if anchor and anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=UTC)
            age_minutes = int((now - anchor).total_seconds() // 60) if anchor else -1
            timeout_minutes = int(timeout_hours * 60) if timeout_hours is not None else get_stage_stale_timeout_minutes(job.current_stage)
            print(
                f"  Job {job.id}: stage={job.current_stage or 'queued'}, "
                f"status={job.status}, age={age_minutes}m, timeout={timeout_minutes}m"
            )

            if dry_run:
                continue

            video = db.get(Video, job.video_id) if job.video_id else None
            record_pipeline_failure(
                db,
                job,
                video=video,
                stage=job.current_stage or "queued",
                error=RuntimeError(
                    f"Stale job reaped after {age_minutes} minutes in stage "
                    f"'{job.current_stage or 'queued'}'"
                ),
                default_message=(
                    f"Marked failed by stale-job reaper after {age_minutes} minutes in "
                    f"stage '{job.current_stage or 'queued'}'."
                ),
                stale_reap=True,
            )
            reaped += 1

        if not dry_run and reaped:
            db.commit()

    return reaped


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reap stale transcription jobs")
    parser.add_argument("--dry-run", action="store_true", help="Only show stale jobs, don't mark them failed")
    parser.add_argument(
        "--timeout-hours",
        type=float,
        default=None,
        help="Legacy global timeout override. If omitted, stage-aware timeouts are used.",
    )
    args = parser.parse_args()

    count = reap_stale_jobs(args.dry_run, timeout_hours=args.timeout_hours)
    raise SystemExit(0 if count == 0 else 1)
