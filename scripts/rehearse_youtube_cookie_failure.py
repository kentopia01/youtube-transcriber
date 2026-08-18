#!/usr/bin/env python3
"""Rehearse guarded cookie failure handling without touching production state."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.runtime_config import load_native_env

load_native_env(PROJECT_ROOT)

from app.config import settings
from app.services.youtube_cookie_profiles import (
    PROFILE_A,
    PROFILE_B,
    CookieProfileError,
    activate_profile,
    configured_cookie_files,
    load_profile_state,
    profile_state_path,
    record_profile_probe,
    resolve_active_profile,
)
from scripts import refresh_youtube_cookies as refresh


def file_hash(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SyntheticExportFailure:
    def __init__(self, _options: dict[str, object]) -> None:
        pass

    def __enter__(self) -> "SyntheticExportFailure":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def extract_info(self, _url: str, *, download: bool) -> None:
        del download
        raise refresh.CookieRefreshError("synthetic export failure")


def run_rehearsal() -> dict[str, object]:
    production_files = configured_cookie_files()
    production_cookie = production_files[PROFILE_A]
    production_state = profile_state_path()
    if production_cookie is None or not production_cookie.is_file():
        raise RuntimeError("production Profile A cookie jar is not configured")
    if not production_state.is_file():
        raise RuntimeError("production cookie-profile state is missing")
    if resolve_active_profile(production_state) != PROFILE_A:
        raise RuntimeError("production Profile A is not active")
    if production_files[PROFILE_B] is not None:
        raise RuntimeError("Profile B is configured; this rehearsal is no longer valid")
    before = {
        "active_profile": resolve_active_profile(production_state),
        "cookie_sha256": file_hash(production_cookie),
        "state_sha256": file_hash(production_state),
    }

    with tempfile.TemporaryDirectory(prefix="yt-cookie-failure-rehearsal-") as raw:
        root = Path(raw)
        profile_root = root / "browser-profile"
        profile_root.mkdir()
        cookie_file = root / "profile-a.txt"
        cookie_file.write_text(
            "# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSAPISID\trehearsal-only\n",
            encoding="utf-8",
        )
        cookie_file.chmod(0o600)
        evidence_file = root / "refresh-evidence.json"
        state_file = root / "profile-state.json"
        last_good_hash = file_hash(cookie_file)

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(settings, "ytdlp_cookies_file", str(cookie_file))
            )
            stack.enter_context(
                patch.object(settings, "ytdlp_cookie_profile_b_file", "")
            )
            stack.enter_context(
                patch.object(settings, "ytdlp_cookie_profile_state_file", str(state_file))
            )
            stack.enter_context(
                patch.object(
                    settings,
                    "ytdlp_cookie_profile_failure_cooldown_seconds",
                    1800,
                )
            )
            stack.enter_context(
                patch.object(refresh.yt_dlp, "YoutubeDL", SyntheticExportFailure)
            )

            refresh_error = None
            try:
                refresh.refresh_cookie_jar(
                    profile_root=profile_root,
                    cookie_file=cookie_file,
                    evidence_file=evidence_file,
                    probe_url="https://www.youtube.com/watch?v=rehearsal",
                    profile_resource="rehearsal:profile-a",
                )
            except refresh.CookieRefreshError as exc:
                refresh_error = str(exc)

            record_profile_probe(
                PROFILE_A,
                ok=False,
                error="synthetic rehearsal failure",
                state_path=state_file,
            )
            activation_errors: dict[str, str] = {}
            for target in (PROFILE_A, PROFILE_B):
                try:
                    activate_profile(target, state_path=state_file)
                except CookieProfileError as exc:
                    activation_errors[target] = str(exc)

            rehearsal_state = load_profile_state(state_file)
            refresh_evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
            rehearsal = {
                "refresh_failed": refresh_error == "synthetic export failure",
                "production_not_replaced": not refresh_evidence["production_replaced"],
                "last_good_preserved": file_hash(cookie_file) == last_good_hash,
                "active_profile_remained_a": resolve_active_profile(state_file)
                == PROFILE_A,
                "profile_a_cooldown_recorded": bool(
                    rehearsal_state["profiles"][PROFILE_A]["cooldown_until"]
                ),
                "profile_a_activation_blocked": "cooling down"
                in activation_errors.get(PROFILE_A, ""),
                "profile_b_unconfigured": "not configured"
                in activation_errors.get(PROFILE_B, ""),
                "failed_evidence_recorded": refresh_evidence["status"] == "failed",
            }

    after = {
        "active_profile": resolve_active_profile(production_state),
        "cookie_sha256": file_hash(production_cookie),
        "state_sha256": file_hash(production_state),
    }
    checks = {
        **rehearsal,
        "production_active_profile_unchanged": before["active_profile"]
        == after["active_profile"],
        "production_cookie_unchanged": before["cookie_sha256"]
        == after["cookie_sha256"],
        "production_state_unchanged": before["state_sha256"]
        == after["state_sha256"],
    }
    return {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "finished_at": datetime.now(UTC).isoformat(),
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = run_rehearsal()
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
