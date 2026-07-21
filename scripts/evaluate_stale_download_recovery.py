#!/usr/bin/env python3
"""Read-only T061 inventory and metadata probe for stale download failures."""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.runtime_config import load_native_env, resolve_sync_database_url  # noqa: E402


@dataclass(frozen=True)
class Candidate:
    job_id: str
    video_id: str
    youtube_video_id: str
    title: str
    url: str
    failed_at: str


@dataclass(frozen=True)
class Evaluation:
    candidate: Candidate
    category: str
    duration_seconds: float | None = None
    availability: str | None = None
    live_status: str | None = None
    current_title: str | None = None
    detail: str | None = None


def classify_metadata(
    candidate: Candidate,
    info: dict[str, Any],
    *,
    min_duration_seconds: int,
    max_duration_seconds: int,
) -> Evaluation:
    duration = info.get("duration")
    duration_value = float(duration) if duration is not None else None
    availability = str(info.get("availability") or "public")
    live_status = str(info.get("live_status") or "not_live")
    fields = {
        "candidate": candidate,
        "duration_seconds": duration_value,
        "availability": availability,
        "live_status": live_status,
        "current_title": info.get("title"),
    }
    if availability not in {"public", "unlisted"}:
        return Evaluation(category="unavailable", detail=f"availability={availability}", **fields)
    if live_status in {"is_upcoming", "is_live", "post_live"}:
        return Evaluation(category="live_or_scheduled", detail=f"live_status={live_status}", **fields)
    if duration_value is None:
        return Evaluation(category="needs_review", detail="duration unavailable", **fields)
    if duration_value < min_duration_seconds:
        return Evaluation(category="short_form", detail=f"below {min_duration_seconds}s floor", **fields)
    if duration_value > max_duration_seconds:
        return Evaluation(category="duration_limit", detail=f"above {max_duration_seconds}s limit", **fields)
    return Evaluation(category="eligible", detail="public long-form candidate", **fields)


def load_candidates(db_url: str, *, include_retried: bool = False) -> list[Candidate]:
    newer_attempt_filter = "" if include_retried else """
          AND NOT EXISTS (
              SELECT 1 FROM jobs newer
              WHERE newer.video_id = j.video_id
                AND newer.job_type = 'pipeline'
                AND newer.created_at > j.created_at
          )
    """
    visibility_filter = "" if include_retried else "AND j.hidden_from_queue = false"
    sql = text(f"""
        SELECT
            j.id AS job_id,
            v.id AS video_id,
            v.youtube_video_id,
            v.title,
            v.url,
            j.created_at AS failed_at
        FROM jobs j
        JOIN videos v ON v.id = j.video_id
        WHERE j.job_type = 'pipeline'
          AND j.status = 'failed'
          {visibility_filter}
          AND j.current_stage = 'download'
          AND j.recovery_status = 'stale_reaped'
          {newer_attempt_filter}
        ORDER BY j.created_at, j.id
    """)
    engine = create_engine(db_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            rows = connection.execute(sql).mappings().all()
    finally:
        engine.dispose()
    return [
        Candidate(
            job_id=str(row["job_id"]),
            video_id=str(row["video_id"]),
            youtube_video_id=row["youtube_video_id"],
            title=row["title"],
            url=row["url"],
            failed_at=row["failed_at"].isoformat(),
        )
        for row in rows
    ]


def probe_candidate(candidate: Candidate, min_duration: int, max_duration: int) -> Evaluation:
    import yt_dlp

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 1,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(candidate.url, download=False)
        return classify_metadata(
            candidate,
            info,
            min_duration_seconds=min_duration,
            max_duration_seconds=max_duration,
        )
    except Exception as exc:  # noqa: BLE001 - probe errors are evaluation output
        return Evaluation(
            candidate=candidate,
            category="probe_error",
            detail=f"{exc.__class__.__name__}: {str(exc)[:300]}",
        )


def render_markdown(evaluations: list[Evaluation]) -> str:
    counts: dict[str, int] = {}
    for item in evaluations:
        counts[item.category] = counts.get(item.category, 0) + 1
    lines = [
        "# T061 stale-download evaluation",
        "",
        "Counts: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())),
        "",
        "| YouTube ID | Category | Duration | Title | Detail |",
        "|---|---|---:|---|---|",
    ]
    for item in evaluations:
        duration = f"{int(item.duration_seconds)}s" if item.duration_seconds is not None else "—"
        title = (item.current_title or item.candidate.title).replace("|", "\\|")
        detail = (item.detail or "").replace("|", "\\|")
        lines.append(
            f"| `{item.candidate.youtube_video_id}` | {item.category} | {duration} | {title} | {detail} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url")
    parser.add_argument("--probe", action="store_true", help="Fetch current YouTube metadata; never downloads media")
    parser.add_argument(
        "--include-retried",
        action="store_true",
        help="Include hidden historical stale jobs that already have a newer attempt",
    )
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    load_native_env(PROJECT_ROOT)
    from app.config import settings

    db_url = resolve_sync_database_url(PROJECT_ROOT, explicit=args.db_url)
    candidates = load_candidates(db_url, include_retried=args.include_retried)
    if not args.probe:
        evaluations = [Evaluation(candidate=item, category="unprobed") for item in candidates]
    else:
        min_duration = settings.auto_ingest_min_duration_seconds
        max_duration = settings.max_video_duration_minutes * 60
        by_id: dict[str, Evaluation] = {}
        with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 4))) as executor:
            futures = {
                executor.submit(probe_candidate, item, min_duration, max_duration): item
                for item in candidates
            }
            for future in as_completed(futures):
                result = future.result()
                by_id[result.candidate.job_id] = result
        evaluations = [by_id[item.job_id] for item in candidates]

    if args.json:
        print(json.dumps([asdict(item) for item in evaluations], indent=2))
    else:
        print(render_markdown(evaluations), end="")
    return 1 if any(item.category == "probe_error" for item in evaluations) else 0


if __name__ == "__main__":
    raise SystemExit(main())
