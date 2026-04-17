"""Video classification — decides whether a YouTube URL is a "regular video"
worth ingesting.

Rejects:
  - YouTube Shorts (duration ≤ ``shorts_max_duration_seconds`` OR ``/shorts/``
    URL path)
  - Live streams that are currently live or upcoming (not yet recorded)

Accepts:
  - Regular uploaded videos of any length
  - Recordings of past live streams (``live_status='was_live'``)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()


SHORTS_MAX_DURATION_SECONDS = 60


@dataclass
class ClassificationResult:
    is_regular: bool
    reason: str | None  # populated only when is_regular is False

    def __bool__(self) -> bool:
        return self.is_regular


def classify_video_info(info: dict[str, Any]) -> ClassificationResult:
    """Classify a video from its yt-dlp metadata dict.

    Only rejects for signals we can verify from the metadata. On any
    ambiguity, the video is considered regular (accepted). The user can
    always `/unsubscribe` a noisy channel or review via the library.
    """
    live_status = (info.get("live_status") or "").lower()
    is_live = info.get("is_live")
    url = info.get("webpage_url") or info.get("url") or ""
    duration = info.get("duration")

    if is_live is True or live_status in {"is_live", "is_upcoming"}:
        return ClassificationResult(False, f"live_status={live_status or 'is_live'}")

    if "/shorts/" in url.lower():
        return ClassificationResult(False, "url contains /shorts/")

    if duration is not None:
        try:
            d = int(duration)
        except (TypeError, ValueError):
            d = None
        if d is not None and 0 < d <= SHORTS_MAX_DURATION_SECONDS:
            return ClassificationResult(False, f"duration {d}s ≤ {SHORTS_MAX_DURATION_SECONDS}s (likely Short)")

    return ClassificationResult(True, None)


def classify_video_url(url: str) -> ClassificationResult:
    """Look up video metadata via yt-dlp and classify.

    Raises nothing — on any yt-dlp error we fail *open* (treat as regular)
    to avoid silently dropping legit videos when the network is flaky.
    """
    try:
        from app.services.youtube import get_video_info

        info = get_video_info(url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("classify_video_lookup_failed", url=url, error=str(exc))
        # Fail-open: let the downstream submit attempt surface the real error
        return ClassificationResult(True, None)

    return classify_video_info(info)
