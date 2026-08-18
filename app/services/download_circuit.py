"""Bounded Redis circuit for clustered YouTube access degradation.

The circuit protects autonomous subscription ingest only. Manual submissions
remain available, and failures to inspect/update circuit state fail open so an
observability dependency cannot take down the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any

import structlog

from app.config import settings

logger = structlog.get_logger()

_FAILURE_SET_KEY = "youtube-transcriber:download-access:distinct-failures"
_OPEN_KEY = "youtube-transcriber:download-access:open"

ACCESS_DEGRADATION_MARKERS = (
    "http error 403",
    "403 forbidden",
    "http error 429",
    "too many requests",
    "sign in to confirm you",
    "confirm you’re not a bot",
    "confirm you're not a bot",
    "login required",
    "authentication required",
    "po token",
    "sabr",
)


@dataclass(slots=True)
class DownloadCircuitState:
    open: bool
    retry_after_seconds: int = 0
    failure_count: int = 0
    reason: str | None = None
    available: bool = True


def is_youtube_access_degradation(value: str | BaseException | None) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in ACCESS_DEGRADATION_MARKERS)


def _redis_client():
    import redis

    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def _closed(*, available: bool = True) -> DownloadCircuitState:
    return DownloadCircuitState(open=False, available=available)


def get_download_circuit_state(*, client=None, now: float | None = None) -> DownloadCircuitState:
    if not settings.download_circuit_enabled:
        return _closed()

    now = time.time() if now is None else now
    try:
        raw = (client or _redis_client()).get(_OPEN_KEY)
        if not raw:
            return _closed()
        payload = json.loads(raw)
        open_until = float(payload.get("open_until") or 0)
        remaining = max(0, int(open_until - now))
        if remaining <= 0:
            (client or _redis_client()).delete(_OPEN_KEY)
            return _closed()
        return DownloadCircuitState(
            open=True,
            retry_after_seconds=remaining,
            failure_count=int(payload.get("failure_count") or 0),
            reason=str(payload.get("reason") or "youtube_access_degradation"),
        )
    except Exception as exc:  # noqa: BLE001 - fail-open observability boundary
        logger.warning(
            "download_circuit_read_failed",
            exception_type=exc.__class__.__name__,
            error_message=str(exc)[:300],
            outcome="fail_open",
        )
        return _closed(available=False)


def record_download_access_failure(
    video_id: str,
    error: str | BaseException,
    *,
    client=None,
    now: float | None = None,
) -> DownloadCircuitState:
    if not settings.download_circuit_enabled or not is_youtube_access_degradation(error):
        return get_download_circuit_state(client=client, now=now)

    redis_client = client or _redis_client()
    now = time.time() if now is None else now
    try:
        redis_client.sadd(_FAILURE_SET_KEY, str(video_id))
        redis_client.expire(_FAILURE_SET_KEY, settings.download_circuit_window_seconds)
        failure_count = int(redis_client.scard(_FAILURE_SET_KEY))
        if failure_count < settings.download_circuit_failure_threshold:
            return DownloadCircuitState(open=False, failure_count=failure_count)

        open_until = now + settings.download_circuit_cooldown_seconds
        reason = "clustered_youtube_access_degradation"
        redis_client.set(
            _OPEN_KEY,
            json.dumps(
                {
                    "open_until": open_until,
                    "failure_count": failure_count,
                    "reason": reason,
                },
                sort_keys=True,
            ),
            ex=settings.download_circuit_cooldown_seconds,
        )
        state = DownloadCircuitState(
            open=True,
            retry_after_seconds=settings.download_circuit_cooldown_seconds,
            failure_count=failure_count,
            reason=reason,
        )
        logger.warning(
            "download_circuit_opened",
            failure_count=failure_count,
            retry_after_seconds=state.retry_after_seconds,
            video_id=str(video_id),
        )
        return state
    except Exception as exc:  # noqa: BLE001 - fail-open side effect
        logger.warning(
            "download_circuit_update_failed",
            exception_type=exc.__class__.__name__,
            error_message=str(exc)[:300],
            outcome="fail_open",
            video_id=str(video_id),
        )
        return _closed(available=False)


def record_download_access_success(*, client=None) -> None:
    if not settings.download_circuit_enabled:
        return
    try:
        (client or _redis_client()).delete(_FAILURE_SET_KEY, _OPEN_KEY)
    except Exception as exc:  # noqa: BLE001 - fail-open side effect
        logger.warning(
            "download_circuit_close_failed",
            exception_type=exc.__class__.__name__,
            error_message=str(exc)[:300],
            outcome="ignored",
        )


def circuit_state_payload(state: DownloadCircuitState) -> dict[str, Any]:
    return {
        "open": state.open,
        "retry_after_seconds": state.retry_after_seconds,
        "failure_count": state.failure_count,
        "reason": state.reason,
        "available": state.available,
    }
