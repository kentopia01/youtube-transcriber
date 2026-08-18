"""Resolve and persist explicit YouTube cookie-profile selection.

This module never reads browser profiles and never changes the active slot in
response to a download failure. It only resolves configured cookie jars and
stores non-secret operator state.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterator

from app.config import settings

PROFILE_A = "profile_a"
PROFILE_B = "profile_b"
PROFILE_NAMES = (PROFILE_A, PROFILE_B)
STATE_SCHEMA_VERSION = 1


class CookieProfileError(RuntimeError):
    """Raised when a requested cookie-profile operation is not safe."""


def configured_cookie_files() -> dict[str, Path | None]:
    """Return configured named jars while preserving the legacy A setting."""
    profile_a = str(settings.ytdlp_cookies_file or "").strip()
    profile_b = str(settings.ytdlp_cookie_profile_b_file or "").strip()
    return {
        PROFILE_A: Path(profile_a).expanduser() if profile_a else None,
        PROFILE_B: Path(profile_b).expanduser() if profile_b else None,
    }


def profile_state_path() -> Path:
    configured = str(settings.ytdlp_cookie_profile_state_file or "").strip()
    if configured:
        return Path(configured).expanduser()
    profile_a = configured_cookie_files()[PROFILE_A]
    parent = profile_a.parent if profile_a is not None else Path("data/cookies")
    return parent / "youtube-cookie-profiles.json"


def _default_profile_record() -> dict[str, Any]:
    return {
        "last_probe_at": None,
        "last_probe_ok": None,
        "last_error": None,
        "cooldown_until": None,
    }


def _default_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "active_profile": PROFILE_A,
        "updated_at": None,
        "profiles": {name: _default_profile_record() for name in PROFILE_NAMES},
    }


def _safe_profile_record(value: object) -> dict[str, Any]:
    default = _default_profile_record()
    if not isinstance(value, dict):
        return default
    return {
        key: value.get(key)
        if isinstance(value.get(key), (str, bool, type(None)))
        else default[key]
        for key in default
    }


def load_profile_state(path: Path | None = None) -> dict[str, Any]:
    """Read state with fail-safe fallback to Profile A."""
    target = path or profile_state_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return _default_state()
    if not isinstance(raw, dict) or raw.get("schema_version") != STATE_SCHEMA_VERSION:
        return _default_state()

    active = raw.get("active_profile")
    if active not in PROFILE_NAMES:
        active = PROFILE_A
    profiles = raw.get("profiles") if isinstance(raw.get("profiles"), dict) else {}
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "active_profile": active,
        "updated_at": raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else None,
        "profiles": {
            name: _safe_profile_record(profiles.get(name)) for name in PROFILE_NAMES
        },
    }


def _write_profile_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
        tmp.chmod(0o600)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


@contextmanager
def profile_state_lock(path: Path | None = None) -> Iterator[Path]:
    state_path = path or profile_state_path()
    lock_path = state_path.with_name(f"{state_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.chmod(lock_path, 0o600)
    with os.fdopen(descriptor, "r+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield state_path
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def resolve_active_profile(path: Path | None = None) -> str:
    """Return the safe active name; invalid or unconfigured B falls back to A."""
    state = load_profile_state(path)
    active = state["active_profile"]
    if active == PROFILE_B and configured_cookie_files()[PROFILE_B] is None:
        return PROFILE_A
    return active


def resolve_active_cookie_file(path: Path | None = None) -> str | None:
    """Return the selected jar path without requiring the file to exist."""
    selected = configured_cookie_files()[resolve_active_profile(path)]
    return str(selected) if selected is not None else None


def record_profile_probe(
    profile: str,
    *,
    ok: bool,
    error: str | None = None,
    now: datetime | None = None,
    state_path: Path | None = None,
) -> dict[str, Any]:
    if profile not in PROFILE_NAMES:
        raise CookieProfileError(f"unknown cookie profile: {profile}")
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    cooldown_seconds = max(0, settings.ytdlp_cookie_profile_failure_cooldown_seconds)
    with profile_state_lock(state_path) as target:
        state = load_profile_state(target)
        record = state["profiles"][profile]
        record["last_probe_at"] = current_time.isoformat()
        record["last_probe_ok"] = ok
        record["last_error"] = None if ok else str(error or "probe failed")[:400]
        record["cooldown_until"] = (
            None
            if ok
            else (current_time + timedelta(seconds=cooldown_seconds)).isoformat()
        )
        state["updated_at"] = current_time.isoformat()
        _write_profile_state(target, state)
        return state


def activate_profile(
    profile: str,
    *,
    now: datetime | None = None,
    state_path: Path | None = None,
) -> dict[str, Any]:
    """Activate a configured profile after a recent successful probe."""
    if profile not in PROFILE_NAMES:
        raise CookieProfileError(f"unknown cookie profile: {profile}")
    if configured_cookie_files()[profile] is None:
        raise CookieProfileError(f"{profile} is not configured")

    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    max_age = max(0, settings.ytdlp_cookie_profile_probe_max_age_seconds)
    with profile_state_lock(state_path) as target:
        state = load_profile_state(target)
        record = state["profiles"][profile]
        cooldown_until = _parse_time(record.get("cooldown_until"))
        if cooldown_until is not None and cooldown_until > current_time:
            raise CookieProfileError(
                f"{profile} is cooling down until {cooldown_until.isoformat()}"
            )
        probed_at = _parse_time(record.get("last_probe_at"))
        if record.get("last_probe_ok") is not True or probed_at is None:
            raise CookieProfileError(f"{profile} has no successful probe")
        if current_time - probed_at > timedelta(seconds=max_age):
            raise CookieProfileError(f"{profile} probe evidence is stale")

        state["active_profile"] = profile
        state["updated_at"] = current_time.isoformat()
        _write_profile_state(target, state)
        return state
