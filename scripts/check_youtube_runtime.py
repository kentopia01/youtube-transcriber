#!/usr/bin/env python3
"""Fail closed when a supported YouTube extraction runtime has drifted."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.youtube_runtime import inspect_youtube_runtime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check yt-dlp and JavaScript runtime parity")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    status = inspect_youtube_runtime()
    if args.json:
        print(json.dumps(status.as_dict(), indent=2, sort_keys=True))
    else:
        print(
            f"youtube_runtime={'ok' if status.ok else 'degraded'} "
            f"yt_dlp={status.yt_dlp_version} "
            f"required={status.required_yt_dlp_version} "
            f"js_runtime={status.js_runtime} "
            f"js_available={bool(status.js_runtime_path)}"
        )
    return 0 if status.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
