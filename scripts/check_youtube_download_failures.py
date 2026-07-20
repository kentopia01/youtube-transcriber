#!/usr/bin/env python3
"""Alert when a recent batch has repeated YouTube download-stage 403s."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.services.runtime_config import load_native_env

load_native_env(PROJECT_ROOT)

from app.services.youtube_download_hardening import (
    create_native_sync_engine,
    get_ytdlp_version_health,
    inspect_cookie_file,
    summarize_recent_download_403_failures,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check recent YouTube download 403 failures")
    parser.add_argument("--hours", type=float, default=4.0)
    parser.add_argument("--threshold", type=int, default=3)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    engine = create_native_sync_engine(PROJECT_ROOT)
    with Session(engine) as db:
        summary = summarize_recent_download_403_failures(
            db,
            hours=args.hours,
            threshold=args.threshold,
            limit=args.limit,
        )

    cookie = inspect_cookie_file()
    version = get_ytdlp_version_health()
    payload = {
        "count": summary.count,
        "threshold": args.threshold,
        "since": summary.since.isoformat(),
        "signature": summary.signature,
        "videos": summary.videos,
        "cookie": asdict(cookie),
        "yt_dlp": asdict(version),
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"download_403_failures={summary.count} threshold={args.threshold}")
        for video in summary.videos:
            print(f"- {video.get('youtube_video_id')}: {video.get('title')}")
        print(f"cookie_status={cookie.status} yt_dlp={version.version} yt_dlp_status={version.status}")

    if summary.threshold_met and args.notify:
        from app.services.telegram_notify import notify

        notify("ops.youtube_download_degraded", payload)

    return 1 if summary.threshold_met else 0


if __name__ == "__main__":
    raise SystemExit(main())
