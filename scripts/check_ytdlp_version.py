#!/usr/bin/env python3
"""Warn when the native yt-dlp install is old enough to merit operator review."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.services.runtime_config import load_native_env

load_native_env(PROJECT_ROOT)

from app.services.youtube_download_hardening import get_ytdlp_version_health


def main() -> int:
    parser = argparse.ArgumentParser(description="Check yt-dlp version freshness")
    parser.add_argument("--warn-days", type=int, default=75)
    args = parser.parse_args()
    health = get_ytdlp_version_health(warn_days=args.warn_days)
    print(f"yt-dlp {health.version} status={health.status} age_days={health.age_days}")
    if health.warning:
        print(f"warning: {health.warning}")
    return 1 if health.status == "old" else 0


if __name__ == "__main__":
    raise SystemExit(main())
