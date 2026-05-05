#!/usr/bin/env python3
"""Retry recent transient cleanup/summarize provider failures safely.

Usage:
  python scripts/auto_retry_transient_failures.py --dry-run
  python scripts/auto_retry_transient_failures.py --limit 10 --max-age-hours 12
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.services.transient_auto_retry import (
    DEFAULT_LIMIT,
    DEFAULT_MAX_AGE_HOURS,
    retry_transient_failures,
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Retry transient cleanup/summarize provider failures")
    parser.add_argument("--dry-run", action="store_true", help="Plan retries without enqueueing")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Maximum failed jobs to inspect")
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=DEFAULT_MAX_AGE_HOURS,
        help="Only consider failures newer than this many hours",
    )
    args = parser.parse_args()

    engine = create_engine(_resolve_db_url_sync())
    with Session(engine) as db:
        decisions = retry_transient_failures(
            db,
            dry_run=args.dry_run,
            limit=args.limit,
            max_age_hours=args.max_age_hours,
        )

    if not decisions:
        print("No failed pipeline jobs inspected")
        return 0

    counts = Counter(decision.status for decision in decisions)
    for decision in decisions:
        suffix = ""
        if decision.start_from:
            suffix += f" start_from={decision.start_from}"
        if decision.new_job_id:
            suffix += f" new_job_id={decision.new_job_id}"
        if decision.active_job_id:
            suffix += f" active_job_id={decision.active_job_id}"
        print(
            f"{decision.status.upper()}: job={decision.job_id} "
            f"video={decision.video_id or '-'} reason={decision.reason}{suffix}"
        )

    print(
        "Summary: "
        + ", ".join(f"{status}={count}" for status, count in sorted(counts.items()))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
