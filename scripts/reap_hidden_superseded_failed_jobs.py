#!/usr/bin/env python3
"""Delete hidden superseded failed jobs older than a retention window.

Usage:
  python scripts/reap_hidden_superseded_failed_jobs.py [--retention-days 14] [--dry-run]
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone

import psycopg2


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reap_hidden_superseded_failed_jobs(db_url: str, retention_days: int, dry_run: bool) -> int:
    """Find hidden superseded failed jobs older than retention and delete them."""
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cur.execute(
        """
        SELECT id, video_id, hidden_at, superseded_by_job_id
        FROM jobs
        WHERE status = 'failed'
          AND hidden_from_queue = TRUE
          AND hidden_reason = 'superseded'
          AND superseded_by_job_id IS NOT NULL
          AND hidden_at IS NOT NULL
          AND hidden_at < %s
        ORDER BY hidden_at ASC
        """,
        (cutoff,),
    )

    stale_hidden = cur.fetchall()
    if not stale_hidden:
        print(f"No hidden superseded failed jobs to delete (retention: {retention_days}d)")
        conn.close()
        return 0

    print(f"Found {len(stale_hidden)} hidden superseded failed job(s) older than {retention_days}d:")
    for job_id, video_id, hidden_at, superseded_by_job_id in stale_hidden:
        age = datetime.now(timezone.utc) - _as_utc(hidden_at)
        print(
            f"  Job {job_id}: video={video_id}, superseded_by={superseded_by_job_id}, hidden_for={age}"
        )

        if not dry_run:
            cur.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
            print("    → Deleted")

    conn.close()
    return len(stale_hidden)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Delete hidden superseded failed jobs after retention"
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=14,
        help="Delete hidden superseded failed jobs older than this many days (default: 14)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show jobs that would be deleted",
    )
    parser.add_argument(
        "--db-url",
        default="postgresql://transcriber:transcriber@localhost:5432/transcriber",
        help="Database URL",
    )
    args = parser.parse_args(argv)

    reap_hidden_superseded_failed_jobs(
        db_url=args.db_url,
        retention_days=args.retention_days,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
