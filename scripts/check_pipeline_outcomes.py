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
from app.services.pipeline_outcome_alerts import (
    DEFAULT_REMINDER_SECONDS,
    decide_pipeline_outcome_alert,
    load_pipeline_outcome_alert_state,
    save_pipeline_outcome_alert_state,
)
from app.services.pipeline_outcomes import collect_pipeline_outcomes
from app.services.runtime_config import load_native_env, resolve_sync_database_url


def process_exit_code(*, degraded: bool, alert_output: bool) -> int:
    """Separate an observed incident from a watchdog execution failure."""
    if alert_output:
        return 0
    return 1 if degraded else 0


def _run() -> int:
    parser = argparse.ArgumentParser(description="Check recent autonomous pipeline outcomes")
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--failure-threshold", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--alert-output",
        action="store_true",
        help="Emit stateful alert/recovery text, or NO_REPLY when no delivery is due",
    )
    parser.add_argument(
        "--alert-state-file",
        type=Path,
        default=PROJECT_ROOT / "data/runtime/pipeline_outcome_alert_state.json",
    )
    parser.add_argument(
        "--alert-reminder-seconds",
        type=int,
        default=DEFAULT_REMINDER_SECONDS,
    )
    args = parser.parse_args()
    if args.alert_output and args.json:
        parser.error("--alert-output and --json cannot be combined")

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
    if args.alert_output:
        state_path = args.alert_state_file.expanduser().resolve()
        previous_state = load_pipeline_outcome_alert_state(state_path)
        decision = decide_pipeline_outcome_alert(
            summary,
            previous_state,
            reminder_seconds=args.alert_reminder_seconds,
        )
        if decision.next_state != previous_state:
            save_pipeline_outcome_alert_state(state_path, decision.next_state)
        print(decision.message or "NO_REPLY")
    elif args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            "pipeline_outcomes "
            f"total={summary.total} completed={summary.completed} failed={summary.failed} "
            f"active={summary.active} overdue={summary.overdue} degraded={summary.degraded}"
        )
    return process_exit_code(
        degraded=summary.degraded,
        alert_output=args.alert_output,
    )


def main() -> int:
    try:
        return _run()
    except Exception as exc:
        if "--alert-output" not in sys.argv:
            raise
        reason = " ".join(str(exc).split())[:240] or "unknown error"
        print(
            "🚨 YouTube pipeline watchdog could not run\n"
            f"{exc.__class__.__name__}: {reason}\n"
            "No pipeline jobs were changed. Manual investigation is required."
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
