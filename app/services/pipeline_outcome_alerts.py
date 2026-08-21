"""Stateful, deterministic alert rendering for pipeline outcome incidents."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.pipeline_outcomes import PipelineOutcomeJob, PipelineOutcomeSummary


ALERT_STATE_VERSION = 1
DEFAULT_REMINDER_SECONDS = 2 * 60 * 60
MAX_ALERT_JOBS = 5


@dataclass(slots=True)
class PipelineOutcomeAlertDecision:
    kind: str
    message: str | None
    next_state: dict[str, Any]


def load_pipeline_outcome_alert_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("version") != ALERT_STATE_VERSION:
        return {}
    return payload


def save_pipeline_outcome_alert_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _incident_fingerprint(summary: PipelineOutcomeSummary) -> str:
    evidence = {
        "failed": sorted(summary.failed_job_ids),
        "overdue": sorted(summary.overdue_job_ids),
    }
    encoded = json.dumps(evidence, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def _compact(value: object, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def _job_lines(job: PipelineOutcomeJob, *, overdue: bool) -> list[str]:
    title = _compact(job.title, limit=80) or "Untitled"
    external_id = job.youtube_video_id or job.video_id or job.job_id
    stage = _compact(job.stage or "unknown", limit=40)
    state = f"overdue at {stage}" if overdue else f"failed at {stage}"
    recovery = (
        _compact(job.recovery_status, limit=50).replace("_", " ")
        if job.recovery_status
        else (f"retry attempt {job.attempt_number}" if job.attempt_number > 1 else "no retry yet")
    )
    lines = [f"• {title} [{external_id}] — {state}; {recovery}"]
    reason = _compact(job.error_message, limit=180)
    if reason:
        lines.append(f"  Reason: {reason}")
    return lines


def _window_label(hours: float) -> str:
    return f"{int(hours)}h" if float(hours).is_integer() else f"{hours:g}h"


def render_degraded_pipeline_outcome_alert(
    summary: PipelineOutcomeSummary,
    *,
    kind: str,
    reminder_seconds: int,
) -> str:
    label = {"changed": "Incident changed", "reminder": "Still degraded"}.get(kind)
    lines = ["⚠️ YouTube pipeline degraded"]
    if label:
        lines.append(label)
    lines.extend(
        [
            "",
            (
                f"Last {_window_label(summary.window_hours)}: {summary.total} videos · "
                f"{summary.completed} completed · "
                f"{summary.failed} failed · {summary.overdue} overdue"
            ),
            "",
            "Affected latest outcomes:",
        ]
    )
    details: list[tuple[PipelineOutcomeJob, bool]] = [
        *((job, False) for job in summary.failed_jobs),
        *((job, True) for job in summary.overdue_jobs),
    ]
    for job, overdue in details[:MAX_ALERT_JOBS]:
        lines.extend(_job_lines(job, overdue=overdue))
    omitted = summary.failed + summary.overdue - min(len(details), MAX_ALERT_JOBS)
    if omitted > 0:
        lines.append(f"• …and {omitted} more")
    lines.extend(
        [
            "",
            "The watchdog is read-only: it has not retried or changed these jobs.",
            (
                "Next check in 30m; unchanged incidents remind every "
                f"{max(1, reminder_seconds // 3600)}h."
            ),
        ]
    )
    return "\n".join(lines)


def render_recovered_pipeline_outcome_alert(
    summary: PipelineOutcomeSummary,
    *,
    previous_state: dict[str, Any],
    now: datetime,
) -> str:
    started_at = _parse_timestamp(previous_state.get("incident_started_at"))
    duration = ""
    if started_at is not None:
        minutes = max(0, int((now - started_at).total_seconds() // 60))
        duration = (
            f" after {minutes // 60}h {minutes % 60}m"
            if minutes >= 60
            else f" after {minutes}m"
        )
    return "\n".join(
        [
            "✅ YouTube pipeline watchdog recovered",
            f"The previous degraded incident cleared{duration}.",
            (
                f"Last {_window_label(summary.window_hours)} now: {summary.total} videos · "
                f"{summary.completed} completed · "
                f"{summary.failed} failed · {summary.overdue} overdue"
            ),
        ]
    )


def decide_pipeline_outcome_alert(
    summary: PipelineOutcomeSummary,
    previous_state: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    reminder_seconds: int = DEFAULT_REMINDER_SECONDS,
) -> PipelineOutcomeAlertDecision:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    previous = previous_state or {}
    now_text = now.isoformat()
    was_degraded = previous.get("degraded") is True

    if not summary.degraded:
        if not was_degraded:
            return PipelineOutcomeAlertDecision("healthy", None, previous)
        next_state = {
            "version": ALERT_STATE_VERSION,
            "degraded": False,
            "recovered_at": now_text,
        }
        return PipelineOutcomeAlertDecision(
            "recovered",
            render_recovered_pipeline_outcome_alert(summary, previous_state=previous, now=now),
            next_state,
        )

    fingerprint = _incident_fingerprint(summary)
    previous_fingerprint = previous.get("fingerprint")
    last_alert_at = _parse_timestamp(previous.get("last_alert_at"))
    reminder_due = (
        last_alert_at is None
        or (now - last_alert_at).total_seconds() >= max(60, reminder_seconds)
    )
    if not was_degraded:
        kind = "new"
    elif fingerprint != previous_fingerprint:
        kind = "changed"
    elif reminder_due:
        kind = "reminder"
    else:
        kind = "suppressed"

    incident_started_at = (
        previous.get("incident_started_at") if was_degraded else now_text
    ) or now_text
    next_state = {
        "version": ALERT_STATE_VERSION,
        "degraded": True,
        "fingerprint": fingerprint,
        "incident_started_at": incident_started_at,
        "last_alert_at": now_text if kind != "suppressed" else previous.get("last_alert_at"),
        "failed": summary.failed,
        "overdue": summary.overdue,
    }
    message = None
    if kind != "suppressed":
        message = render_degraded_pipeline_outcome_alert(
            summary,
            kind=kind,
            reminder_seconds=reminder_seconds,
        )
    return PipelineOutcomeAlertDecision(kind, message, next_state)
