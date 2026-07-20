#!/usr/bin/env python3
"""Probe YouTube metadata/media download health for cookie and no-cookie paths."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.services.runtime_config import load_native_env

load_native_env(PROJECT_ROOT)

from app.config import settings
from app.services.youtube_download_hardening import (
    get_ytdlp_version_health,
    inspect_cookie_file,
    probe_youtube_media_download,
)

DEFAULT_PROBE_URL = "https://www.youtube.com/watch?v=OCEVqy8kl7Q"


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe yt-dlp download health")
    parser.add_argument("--url", default=DEFAULT_PROBE_URL)
    parser.add_argument("--cookie-file", default=settings.ytdlp_cookies_file)
    parser.add_argument("--test-download", action="store_true", help="Use yt-dlp test mode instead of a full media download")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cookie = inspect_cookie_file(args.cookie_file)
    version = get_ytdlp_version_health()
    with_cookies = probe_youtube_media_download(
        args.url,
        use_cookies=True,
        test_download=args.test_download,
        cookie_path=args.cookie_file,
    )
    without_cookies = probe_youtube_media_download(
        args.url,
        use_cookies=False,
        test_download=args.test_download,
    )
    result = {
        "cookie": asdict(cookie),
        "yt_dlp": asdict(version),
        "with_cookies": asdict(with_cookies),
        "without_cookies": asdict(without_cookies),
        "mode": "test" if args.test_download else "full",
    }

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"yt-dlp: {version.version} status={version.status}")
        if version.warning:
            print(f"warning: {version.warning}")
        print(f"cookies: status={cookie.status} count={cookie.cookie_count} auth={cookie.auth_cookie_count}")
        print(f"with_cookies: ok={with_cookies.ok} error={with_cookies.error or '-'}")
        print(f"without_cookies: ok={without_cookies.ok} error={without_cookies.error or '-'}")

    if not without_cookies.ok:
        return 2
    if cookie.exists and not with_cookies.ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
