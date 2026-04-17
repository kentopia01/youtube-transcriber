import os
import re
from urllib.parse import urlsplit, urlunsplit

import structlog
import yt_dlp

from app.config import settings

logger = structlog.get_logger()


def _apply_cookie_opts(ydl_opts: dict) -> dict:
    """Inject yt-dlp cookie options from settings."""
    if settings.ytdlp_cookies_file and os.path.exists(settings.ytdlp_cookies_file):
        ydl_opts["cookiefile"] = settings.ytdlp_cookies_file
    elif settings.ytdlp_cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = (settings.ytdlp_cookies_from_browser,)
    return ydl_opts


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
    _apply_cookie_opts(ydl_opts)

    url = f"https://www.youtube.com/watch?v={video_id}"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

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
        "skip_download": True,
    }
    _apply_cookie_opts(ydl_opts)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

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
    _apply_cookie_opts(ydl_opts)

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

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(discovery_url, download=False)

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
