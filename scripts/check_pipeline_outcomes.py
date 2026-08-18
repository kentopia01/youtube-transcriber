#!/usr/bin/env python3
"""Read-only completion watchdog for recent autonomous pipeline attempts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.services.pipeline_outcomes import collect_pipeline_outcomes
from app.services.runtime_config import load_native_env, resolve_sync_database_url


def main() -> int:
    parser = argparse.ArgumentParser(description="Check recent autonomous pipeline outcomes")
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--failure-threshold", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    load_native_env(PROJECT_ROOT)
    engine = create_engine(
        resolve_sync_database_url(PROJECT_ROOT, fallback=settings.database_url_sync)
    )
    try:
        with Session(engine) as db:
            summary = collect_pipeline_outcomes(
                db,
                hours=args.hours,
                failure_threshold=args.failure_threshold,
            )
    finally:
        engine.dispose()

    payload = summary.as_dict()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            "pipeline_outcomes "
            f"total={summary.total} completed={summary.completed} failed={summary.failed} "
            f"active={summary.active} overdue={summary.overdue} degraded={summary.degraded}"
        )
    return 1 if summary.degraded else 0


if __name__ == "__main__":
    raise SystemExit(main())
