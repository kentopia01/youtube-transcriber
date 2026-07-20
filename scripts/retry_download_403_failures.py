#!/usr/bin/env python3
"""Retry failed download-stage YouTube 403 jobs with normal attempt guardrails."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.services.runtime_config import load_native_env

load_native_env(PROJECT_ROOT)

from app.services.youtube_download_hardening import create_native_sync_engine, retry_download_403_failures


def _youtube_ids(values: list[str]) -> list[str]:
    ids: list[str] = []
    for value in values:
        for item in value.split(","):
            item = item.strip()
            if item:
                ids.append(item)
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description="Retry failed YouTube download 403 jobs")
    parser.add_argument("--youtube-id", action="append", default=[], help="YouTube id, repeatable or comma-separated")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--max-jobs", type=int, default=None)
    parser.add_argument("--apply", action="store_true", help="Enqueue retries. Default is dry-run.")
    args = parser.parse_args()

    engine = create_native_sync_engine(PROJECT_ROOT)
    with Session(engine) as db:
        decisions = retry_download_403_failures(
            db,
            youtube_ids=_youtube_ids(args.youtube_id),
            dry_run=not args.apply,
            limit=args.limit,
            max_jobs=args.max_jobs,
        )

    if not decisions:
        print("No matching failed download 403 jobs found")
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
            f"youtube={decision.youtube_video_id or '-'} reason={decision.reason}{suffix}"
        )
    print("Summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
