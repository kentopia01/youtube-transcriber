#!/usr/bin/env python3
"""Reap stale jobs that are stuck in 'running' or 'processing' state.

If the worker crashes mid-transcription, jobs stay in a running state forever.
This script marks them as 'failed' after a configurable timeout.

Usage:
  python scripts/reap_stale_jobs.py [--timeout-hours 2] [--dry-run]
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone

import psycopg2


def reap_stale_jobs(db_url: str, timeout_hours: float, dry_run: bool):
    """Find and mark stale jobs as failed."""
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)

    # Find stale jobs
    cur.execute("""
        SELECT id, video_id, status, started_at, updated_at
        FROM jobs
        WHERE status IN ('running', 'processing', 'downloading', 'transcribing',
                         'diarizing', 'cleaning', 'summarizing', 'embedding')
        AND updated_at < %s
    """, (cutoff,))

    stale_jobs = cur.fetchall()

    if not stale_jobs:
        print(f"No stale jobs found (cutoff: {timeout_hours}h)")
        conn.close()
        return 0

    print(f"Found {len(stale_jobs)} stale job(s):")
    for job_id, video_id, status, started_at, updated_at in stale_jobs:
        age = datetime.now(timezone.utc) - updated_at.replace(tzinfo=timezone.utc)
        print(f"  Job {job_id}: status={status}, stale for {age}")

        if not dry_run:
            cur.execute("""
                UPDATE jobs
                SET status = 'failed',
                    error_message = 'Reaped: job stale for over %s hours (likely worker crash)',
                    completed_at = NOW()
                WHERE id = %s
            """, (timeout_hours, job_id))

            # Also reset the video status so it can be re-submitted
            cur.execute("""
                UPDATE videos
                SET status = 'failed'
                WHERE id = %s AND status IN ('processing', 'downloading', 'transcribing')
            """, (video_id,))

            print(f"    → Marked as failed")

    conn.close()
    return len(stale_jobs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reap stale transcription jobs")
    parser.add_argument("--timeout-hours", type=float, default=2.0,
                        help="Hours after which a running job is considered stale (default: 2)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only show stale jobs, don't mark them as failed")
    parser.add_argument("--db-url", default="postgresql://transcriber:transcriber@localhost:5432/transcriber",
                        help="Database URL")
    args = parser.parse_args()

    count = reap_stale_jobs(args.db_url, args.timeout_hours, args.dry_run)
    sys.exit(0 if count == 0 else 1)
