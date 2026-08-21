import os
import re
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit

import structlog
import yt_dlp
from yt_dlp.utils import DownloadError

from app.services.youtube_cookie_snapshot import immutable_cookie_snapshot
from app.services.youtube_po_token import require_authenticated_access_ready

logger = structlog.get_logger()

_YTDLP_REMOTE_COMPONENTS = ["ejs:github"]

_AUTHENTICATION_REQUIRED_MARKERS = (
    "sign in to confirm your age",
    "sign in to confirm you're not a bot",
    "sign in to confirm you’re not a bot",
    "login required",
    "authentication required",
    "members-only",
    "members only",
    "this video is private",
    "private video",
    "age-restricted",
    "age restricted",
)

_AUTHENTICATED_SESSION_DEGRADATION_MARKERS = (
    "http error 403",
    "forbidden",
    "the page needs to be reloaded",
    "video unavailable",
    "unplayable",
)


@contextmanager
def _authenticated_opts(ydl_opts: dict):
    """Yield authenticated options backed only by a disposable cookie copy."""
    readiness = require_authenticated_access_ready()
    with immutable_cookie_snapshot() as snapshot:
        authenticated = dict(ydl_opts)
        if snapshot:
            authenticated["cookiefile"] = snapshot
            authenticated["extractor_args"] = {
                "youtube": {"player_client": [readiness.client]}
            }
        yield authenticated


def _cookies_enabled(ydl_opts: dict) -> bool:
    return "cookiefile" in ydl_opts or "cookiesfrombrowser" in ydl_opts


def _is_authentication_required_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _AUTHENTICATION_REQUIRED_MARKERS)


def _is_authenticated_session_degradation(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _AUTHENTICATED_SESSION_DEGRADATION_MARKERS)


def _extract_info_anonymous_first(
    url: str,
    ydl_opts: dict,
    *,
    download: bool,
    video_id: str | None,
    purpose: str,
) -> dict:
    """Extract anonymously unless YouTube explicitly requires authentication.

    Public YouTube traffic must not inherit the configured account session. If
    an explicit content/login restriction requires authentication, retry once
    with the configured cookie source. A degraded authenticated player response
    then gets one final exact-URL anonymous attempt; success proves the content
    is public and avoids turning session breakage into a terminal video error.
    """
    anonymous_opts = dict(ydl_opts)
    try:
        with yt_dlp.YoutubeDL(anonymous_opts) as ydl:
            return ydl.extract_info(url, download=download)
    except DownloadError as anonymous_exc:
        if not _is_authentication_required_error(anonymous_exc):
            raise

        with _authenticated_opts(ydl_opts) as authenticated_opts:
            if not _cookies_enabled(authenticated_opts):
                raise

            logger.info(
                "youtube_authenticated_fallback",
                video_id=video_id,
                purpose=purpose,
                reason="anonymous_authentication_required",
            )
            try:
                with yt_dlp.YoutubeDL(authenticated_opts) as ydl:
                    return ydl.extract_info(url, download=download)
            except DownloadError as authenticated_exc:
                if not _is_authenticated_session_degradation(authenticated_exc):
                    raise

                logger.warning(
                    "youtube_authenticated_session_degraded",
                    video_id=video_id,
                    purpose=purpose,
                    reason="exact_url_anonymous_retry",
                    error=str(authenticated_exc),
                )
                with yt_dlp.YoutubeDL(anonymous_opts) as ydl:
                    return ydl.extract_info(url, download=download)


def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", url):
        return url

    patterns = [
        r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"(?:embed/)([a-zA-Z0-9_-]{11})",
        r"(?:shorts/)([a-zA-Z0-9_-]{11})",
        r"(?:live/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def is_channel_url(url: str) -> bool:
    """Check if a URL points to a YouTube channel."""
    channel_patterns = [
        r"youtube\.com/(?:c|channel|user|@)",
        r"youtube\.com/@[\w-]+",
    ]
    return any(re.search(p, url) for p in channel_patterns)


def _channel_videos_url(channel_url: str) -> str:
    """Normalize a YouTube channel URL to its uploads/videos tab."""
    parts = urlsplit(channel_url.strip())
    path = parts.path.rstrip("/")
    if path and not path.endswith("/videos"):
        path = f"{path}/videos"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _normalize_discovered_video_url(entry: dict) -> str:
    """Return a usable watch URL for a discovered channel entry."""
    url = entry.get("webpage_url") or entry.get("url")
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        return url

    video_id = entry.get("id")
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"

    return ""


def download_audio(video_id: str, audio_dir: str) -> dict:
    """Download audio from a YouTube video and convert to 16kHz WAV.

    Returns dict with audio_path, title, description, duration, thumbnail.
    """
    os.makedirs(audio_dir, exist_ok=True)
    output_path = os.path.join(audio_dir, f"{video_id}.wav")

    ydl_opts = {
        "format": "bestaudio/best",
        "remote_components": _YTDLP_REMOTE_COMPONENTS,
        "outtmpl": os.path.join(audio_dir, f"{video_id}.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
            }
        ],
        "postprocessor_args": ["-ar", "16000", "-ac", "1"],
        "quiet": True,
        "no_warnings": True,
    }
    url = f"https://www.youtube.com/watch?v={video_id}"
    info = _extract_info_anonymous_first(
        url,
        ydl_opts,
        download=True,
        video_id=video_id,
        purpose="media_download",
    )

    logger.info("audio_downloaded", video_id=video_id, path=output_path)

    return {
        "audio_path": output_path,
        "title": info.get("title", ""),
        "description": info.get("description", ""),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "published_at": info.get("upload_date"),
    }


def get_video_info(url: str) -> dict:
    """Get metadata for a video without downloading."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "remote_components": _YTDLP_REMOTE_COMPONENTS,
        "skip_download": True,
        # Metadata submission must not fail just because an authenticated
        # player response exposes no selectable media formats. The audio
        # worker performs its own validated format selection later.
        "ignore_no_formats_error": True,
    }
    info = _extract_info_anonymous_first(
        url,
        ydl_opts,
        download=False,
        video_id=extract_video_id(url),
        purpose="metadata",
    )

    return {
        "video_id": info.get("id"),
        "title": info.get("title", ""),
        "description": info.get("description", ""),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "channel_id": info.get("channel_id"),
        "channel_name": info.get("channel"),
        "channel_url": info.get("channel_url"),
        "published_at": info.get("upload_date"),
        "url": info.get("webpage_url", url),
        "is_live": info.get("is_live"),
        "live_status": info.get("live_status"),
    }


def discover_channel_videos(
    channel_url: str,
    *,
    limit: int | None = None,
    after_date: str | None = None,
    before_date: str | None = None,
    min_duration: int | None = None,
    max_duration: int | None = None,
) -> dict:
    """Discover videos from a YouTube channel with optional filtering.

    Returns dict with channel info and list of video metadata.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }
    if limit is not None:
        ydl_opts["playlistend"] = limit

    if after_date or before_date:
        dr_kwargs = {}
        if after_date:
            dr_kwargs["start"] = after_date.replace("-", "")
        if before_date:
            dr_kwargs["end"] = before_date.replace("-", "")
        ydl_opts["daterange"] = yt_dlp.utils.DateRange(**dr_kwargs)

    duration_filters = []
    if min_duration is not None:
        duration_filters.append(f"duration >= {min_duration}")
    if max_duration is not None:
        duration_filters.append(f"duration <= {max_duration}")
    if duration_filters:
        ydl_opts["match_filter"] = yt_dlp.utils.match_filter_func(
            " & ".join(duration_filters)
        )

    discovery_url = _channel_videos_url(channel_url)

    info = _extract_info_anonymous_first(
        discovery_url,
        ydl_opts,
        download=False,
        video_id=None,
        purpose="channel_discovery",
    )

    videos = []
    for entry in info.get("entries", []):
        if entry and entry.get("id"):
            videos.append({
                "video_id": entry.get("id"),
                "title": entry.get("title", "Unknown"),
                "duration": entry.get("duration"),
                "url": _normalize_discovered_video_url(entry),
                "thumbnail": entry.get("thumbnails", [{}])[0].get("url") if entry.get("thumbnails") else None,
                "published_at": entry.get("upload_date"),
            })

    return {
        "channel_name": info.get("channel") or info.get("title", ""),
        "channel_id": info.get("channel_id") or info.get("id", ""),
        "description": info.get("description", ""),
        "thumbnail": info.get("thumbnails", [{}])[0].get("url") if info.get("thumbnails") else None,
        "videos": videos,
    }
