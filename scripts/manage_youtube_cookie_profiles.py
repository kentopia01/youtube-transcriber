#!/usr/bin/env python3
"""Inspect, probe, and explicitly switch named YouTube cookie profiles."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.runtime_config import load_native_env

load_native_env(PROJECT_ROOT)

from app.services.youtube_cookie_profiles import (
    PROFILE_A,
    PROFILE_B,
    PROFILE_NAMES,
    CookieProfileError,
    activate_profile,
    configured_cookie_files,
    load_profile_state,
    profile_state_path,
    record_profile_probe,
    resolve_active_profile,
)
from app.services.youtube_download_hardening import (
    inspect_cookie_file,
    probe_youtube_media_download,
)

DEFAULT_PROBE_URL = "https://www.youtube.com/watch?v=DFImJfJGXl0"


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def status_payload(*, state_path: Path | None = None) -> dict[str, Any]:
    target = state_path or profile_state_path()
    state = load_profile_state(target)
    active = resolve_active_profile(target)
    configured = configured_cookie_files()
    now = datetime.now(UTC)
    profiles: dict[str, Any] = {}
    for name in PROFILE_NAMES:
        cookie_file = configured[name]
        record = state["profiles"][name]
        cooldown_until = _parse_time(record.get("cooldown_until"))
        profiles[name] = {
            "configured": cookie_file is not None,
            "cookie_file": str(cookie_file) if cookie_file is not None else None,
            "health": asdict(inspect_cookie_file(cookie_file)) if cookie_file is not None else None,
            "last_probe_at": record.get("last_probe_at"),
            "last_probe_ok": record.get("last_probe_ok"),
            "last_error": record.get("last_error"),
            "cooldown_until": record.get("cooldown_until"),
            "cooldown_active": cooldown_until is not None and cooldown_until > now,
        }
    return {
        "schema_version": 1,
        "active_profile": active,
        "state_file": str(target),
        "profiles": profiles,
    }


def probe_profile(
    profile: str,
    *,
    probe_url: str,
    state_path: Path | None = None,
) -> dict[str, Any]:
    cookie_file = configured_cookie_files()[profile]
    if cookie_file is None:
        raise CookieProfileError(f"{profile} is not configured")

    health = inspect_cookie_file(cookie_file)
    if health.status != "ok" or not health.has_auth_cookies:
        reason = f"cookie health is {health.status}"
        record_profile_probe(profile, ok=False, error=reason, state_path=state_path)
        raise CookieProfileError(reason)

    probe = probe_youtube_media_download(
        probe_url,
        use_cookies=True,
        test_download=True,
        cookie_path=str(cookie_file),
    )
    if not probe.ok:
        reason = str(probe.error or "media probe failed")[:400]
        record_profile_probe(profile, ok=False, error=reason, state_path=state_path)
        raise CookieProfileError(reason)

    record_profile_probe(profile, ok=True, state_path=state_path)
    return {
        "profile": profile,
        "status": "ok",
        "cookie_health": asdict(health),
        "media_probe": asdict(probe),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage explicit YouTube cookie-profile selection"
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--probe-url", default=DEFAULT_PROBE_URL)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    probe = commands.add_parser("probe")
    probe.add_argument("profile", choices=PROFILE_NAMES)
    activate = commands.add_parser("activate")
    activate.add_argument("profile", choices=PROFILE_NAMES)
    activate.add_argument("--confirm", action="store_true")
    failback = commands.add_parser("failback")
    failback.add_argument("--confirm", action="store_true")
    return parser


def _print(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    if "profiles" in payload:
        print(f"active_profile={payload['active_profile']}")
        for name, profile in payload["profiles"].items():
            health = profile.get("health") or {}
            print(
                f"{name}: configured={str(profile['configured']).lower()} "
                f"health={health.get('status', 'not_configured')} "
                f"probe={profile.get('last_probe_ok')} "
                f"cooldown={str(profile['cooldown_active']).lower()}"
            )
        return
    print(f"profile={payload['profile']} status={payload['status']}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state_path = args.state_file.expanduser().resolve() if args.state_file else None
    try:
        if args.command == "status":
            payload = status_payload(state_path=state_path)
        elif args.command == "probe":
            payload = probe_profile(
                args.profile,
                probe_url=args.probe_url,
                state_path=state_path,
            )
        else:
            if not args.confirm:
                raise CookieProfileError("profile switch refused without --confirm")
            target = args.profile if args.command == "activate" else PROFILE_A
            cookie_file = configured_cookie_files()[target]
            if cookie_file is None:
                raise CookieProfileError(f"{target} is not configured")
            health = inspect_cookie_file(cookie_file)
            if health.status != "ok" or not health.has_auth_cookies:
                reason = f"cookie health is {health.status}"
                record_profile_probe(
                    target,
                    ok=False,
                    error=reason,
                    state_path=state_path,
                )
                raise CookieProfileError(reason)
            state = activate_profile(target, state_path=state_path)
            payload = {
                "profile": target,
                "status": "active",
                "active_profile": state["active_profile"],
            }
    except CookieProfileError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    _print(payload, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
