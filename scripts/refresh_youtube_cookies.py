#!/usr/bin/env python3
"""Safely refresh the production YouTube cookie jar from Nora's brokered profile."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.runtime_config import load_native_env

load_native_env(PROJECT_ROOT)

import yt_dlp

from app.config import settings
from app.services.youtube_download_hardening import (
    ProbeResult,
    inspect_cookie_file,
    probe_youtube_media_download,
)
from app.services.youtube_cookie_profiles import (
    configured_cookie_files,
    record_profile_probe,
)

DEFAULT_PROFILE_ROOT = Path(
    os.environ.get(
        "YTDLP_BROWSER_PROFILE_ROOT",
        "~/.openclaw/browser/nora-work/user-data",
    )
).expanduser()
_DEFAULT_PROBE_URL_TEXT = os.environ.get(
    "YTDLP_COOKIE_REFRESH_PROBE_URLS",
    os.environ.get(
        "YTDLP_COOKIE_REFRESH_PROBE_URL",
        (
            "https://www.youtube.com/watch?v=DFImJfJGXl0,"
            "https://www.youtube.com/watch?v=jNQXAC9IVRw"
        ),
    ),
)
DEFAULT_PROBE_URLS = tuple(
    value.strip() for value in _DEFAULT_PROBE_URL_TEXT.split(",") if value.strip()
)
DEFAULT_BROKER = Path(
    os.environ.get(
        "BROWSER_BROKER_BIN",
        "~/.openclaw/bin/browser-broker",
    )
).expanduser()
REMOTE_COMPONENTS = ["ejs:github"]
ALLOWED_COOKIE_DOMAINS = (
    "googlevideo.com",
    "youtu.be",
    "youtube.com",
    "youtube-nocookie.com",
)


class CookieRefreshError(RuntimeError):
    """Raised when a candidate jar must not replace production state."""


def _cookie_domain(raw_line: str) -> str | None:
    line = raw_line
    if line.startswith("#HttpOnly_"):
        line = line.removeprefix("#HttpOnly_")
    elif line.startswith("#"):
        return None
    parts = line.split("\t")
    return parts[0].lstrip(".").lower() if len(parts) >= 7 else None


def filter_cookie_jar(path: Path) -> None:
    """Keep only Google/YouTube cookies from the dedicated browser export."""
    kept: list[str] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        domain = _cookie_domain(raw_line)
        if domain is None:
            if not raw_line or raw_line.startswith("# Netscape"):
                kept.append(raw_line)
            continue
        if any(domain == allowed or domain.endswith(f".{allowed}") for allowed in ALLOWED_COOKIE_DOMAINS):
            kept.append(raw_line)
    path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
    path.chmod(0o600)


def _write_evidence(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        tmp.chmod(0o600)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _new_candidate_path(parent: Path) -> Path:
    fd, raw_path = tempfile.mkstemp(prefix=".youtube.refresh.", suffix=".txt", dir=parent)
    os.close(fd)
    candidate = Path(raw_path)
    candidate.unlink()
    return candidate


def _safe_error(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: {str(exc)[:400]}"


def _normalize_probe_urls(
    *,
    probe_url: str | None = None,
    probe_urls: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    values = probe_urls or ((probe_url,) if probe_url else DEFAULT_PROBE_URLS)
    normalized = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
    if len(normalized) < 2 and probe_urls is None and probe_url is None:
        raise CookieRefreshError("at least two default cookie-refresh canaries are required")
    if not normalized:
        raise CookieRefreshError("at least one cookie-refresh canary is required")
    return normalized


def _configured_profile_for_cookie_file(cookie_file: Path) -> str | None:
    target = cookie_file.expanduser().resolve()
    for name, configured in configured_cookie_files().items():
        if configured is not None and configured.expanduser().resolve() == target:
            return name
    return None


@contextmanager
def cookie_jar_lock(cookie_file: Path):
    """Serialize refreshes for one named cookie jar."""
    lock_file = cookie_file.with_name(f"{cookie_file.name}.refresh.lock")
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o600)
    os.chmod(lock_file, 0o600)
    with os.fdopen(descriptor, "r+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _refresh_cookie_jar_unlocked(
    *,
    profile_root: Path,
    cookie_file: Path,
    evidence_file: Path,
    probe_urls: tuple[str, ...],
    profile_resource: str,
) -> dict[str, Any]:
    """Export, validate, probe, and atomically rotate one cookie jar."""
    started_at = datetime.now(UTC)
    evidence: dict[str, Any] = {
        "status": "failed",
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "profile_resource": profile_resource,
        "probe_url": probe_urls[0],
        "probe_urls": list(probe_urls),
        "cookie_health": None,
        "media_probe": None,
        "media_probes": [],
        "production_replaced": False,
        "error": None,
    }

    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    candidate = _new_candidate_path(cookie_file.parent)
    rollback_file = cookie_file.with_name(f"{cookie_file.name}.previous")

    try:
        if not profile_root.is_dir():
            raise CookieRefreshError("browser profile is missing")

        ydl_opts = {
            "cookiesfrombrowser": ("chrome", str(profile_root)),
            "cookiefile": str(candidate),
            "remote_components": REMOTE_COMPONENTS,
            "skip_download": True,
            "ignore_no_formats_error": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(probe_urls[0], download=False)

        if not candidate.exists():
            raise CookieRefreshError("yt-dlp did not produce a cookie jar")
        filter_cookie_jar(candidate)

        health = inspect_cookie_file(candidate)
        evidence["cookie_health"] = asdict(health)
        if health.status != "ok" or not health.has_auth_cookies:
            raise CookieRefreshError(f"candidate cookie health is {health.status}")

        for current_probe_url in probe_urls:
            probe: ProbeResult = probe_youtube_media_download(
                current_probe_url,
                use_cookies=True,
                test_download=True,
                cookie_path=str(candidate),
            )
            probe_payload = asdict(probe)
            probe_payload["url"] = current_probe_url
            evidence["media_probes"].append(probe_payload)
            if evidence["media_probe"] is None:
                evidence["media_probe"] = probe_payload
            if not probe.ok:
                raise CookieRefreshError(
                    "authenticated media probe failed for one canary: "
                    f"{probe.error or 'unknown error'}"
                )

        if cookie_file.exists():
            fd, raw_backup = tempfile.mkstemp(
                prefix=f".{rollback_file.name}.",
                suffix=".tmp",
                dir=cookie_file.parent,
            )
            os.close(fd)
            backup_tmp = Path(raw_backup)
            try:
                shutil.copy2(cookie_file, backup_tmp)
                backup_tmp.chmod(0o600)
                os.replace(backup_tmp, rollback_file)
            finally:
                backup_tmp.unlink(missing_ok=True)

        candidate.chmod(0o600)
        os.replace(candidate, cookie_file)
        profile_name = _configured_profile_for_cookie_file(cookie_file)
        if profile_name is not None:
            record_profile_probe(profile_name, ok=True)
        evidence["production_replaced"] = True
        evidence["status"] = "ok"
        return evidence
    except Exception as exc:
        evidence["error"] = _safe_error(exc)
        profile_name = _configured_profile_for_cookie_file(cookie_file)
        if profile_name is not None:
            try:
                record_profile_probe(profile_name, ok=False, error=evidence["error"])
            except Exception:
                pass
        raise
    finally:
        candidate.unlink(missing_ok=True)
        evidence["finished_at"] = datetime.now(UTC).isoformat()
        _write_evidence(evidence_file, evidence)


def refresh_cookie_jar(
    *,
    profile_root: Path,
    cookie_file: Path,
    evidence_file: Path,
    probe_url: str | None = None,
    probe_urls: list[str] | tuple[str, ...] | None = None,
    profile_resource: str = "identity:nora-work",
) -> dict[str, Any]:
    """Export and rotate one named jar under its own process lock."""
    normalized_probe_urls = _normalize_probe_urls(
        probe_url=probe_url,
        probe_urls=probe_urls,
    )
    with cookie_jar_lock(cookie_file):
        return _refresh_cookie_jar_unlocked(
            profile_root=profile_root,
            cookie_file=cookie_file,
            evidence_file=evidence_file,
            probe_urls=normalized_probe_urls,
            profile_resource=profile_resource,
        )


def build_broker_command(args: argparse.Namespace) -> list[str]:
    key = args.idempotency_key or f"yt-cookie-refresh-{datetime.now().astimezone():%Y%m%d}"
    inner = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--inside-broker",
        "--profile-root",
        str(args.profile_root),
        "--profile-resource",
        args.profile_resource,
        "--cookie-file",
        str(args.cookie_file),
        "--evidence-file",
        str(args.evidence_file),
        "--json",
    ]
    for probe_url in _normalize_probe_urls(
        probe_url=getattr(args, "probe_url", None),
        probe_urls=getattr(args, "probe_urls", None),
    ):
        inner.extend(["--probe-url", probe_url])
    return [
        str(args.broker),
        "run",
        "--resource",
        args.profile_resource,
        "--requester",
        "nora",
        "--priority",
        "p2",
        "--idempotency-key",
        key,
        "--description",
        "Refresh validated YouTube cookie jar",
        "--wait-seconds",
        "120",
        "--lease-seconds",
        "600",
        "--",
        *inner,
    ]


def build_parser() -> argparse.ArgumentParser:
    cookie_default = (
        Path(settings.ytdlp_cookies_file).expanduser()
        if settings.ytdlp_cookies_file
        else None
    )
    parser = argparse.ArgumentParser(description="Refresh YouTube cookies through Nora's brokered profile")
    parser.add_argument("--profile-root", type=Path, default=DEFAULT_PROFILE_ROOT)
    parser.add_argument("--profile-resource", default="identity:nora-work")
    parser.add_argument("--cookie-file", type=Path, default=cookie_default)
    parser.add_argument("--evidence-file", type=Path)
    parser.add_argument(
        "--probe-url",
        dest="probe_urls",
        action="append",
        help="Repeat for each authenticated media canary (default: two stable public videos)",
    )
    parser.add_argument("--broker", type=Path, default=DEFAULT_BROKER)
    parser.add_argument("--idempotency-key")
    parser.add_argument("--inside-broker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cookie_file is None:
        print("YTDLP_COOKIES_FILE is not configured", file=sys.stderr)
        return 2
    args.profile_root = args.profile_root.expanduser().resolve()
    args.cookie_file = args.cookie_file.expanduser().resolve()
    args.evidence_file = (
        args.evidence_file.expanduser().resolve()
        if args.evidence_file
        else args.cookie_file.with_name("youtube-cookie-refresh-status.json")
    )

    if not args.inside_broker:
        if not args.broker.is_file():
            print("browser-broker is unavailable", file=sys.stderr)
            return 2
        return subprocess.run(build_broker_command(args), check=False).returncode

    try:
        evidence = refresh_cookie_jar(
            profile_root=args.profile_root,
            cookie_file=args.cookie_file,
            evidence_file=args.evidence_file,
            probe_urls=args.probe_urls,
            profile_resource=args.profile_resource,
        )
    except Exception as exc:
        print(_safe_error(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    else:
        health = evidence["cookie_health"] or {}
        print(
            "youtube_cookie_refresh=ok "
            f"cookies={health.get('cookie_count', 0)} "
            f"auth={health.get('auth_cookie_count', 0)} "
            "probe=ok"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
