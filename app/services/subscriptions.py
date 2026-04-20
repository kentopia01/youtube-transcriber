"""Channel subscription service — polling, diff detection, CRUD.

Uses the public YouTube RSS feed (no API key needed):
    https://www.youtube.com/feeds/videos.xml?channel_id=<UCxxxx>

RSS cadence lags publish by a few hours, which is fine for a daily poll.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from xml.etree import ElementTree as ET

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.channel_subscription import ChannelSubscription

logger = structlog.get_logger()


RSS_BASE = "https://www.youtube.com/feeds/videos.xml"
YT_RSS_NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}

_VIDEO_URL_RE = re.compile(r"(?:v=|/videos/|/watch\?v=)([A-Za-z0-9_-]{11})")


@dataclass
class FeedEntry:
    video_id: str
    title: str
    url: str
    published_at: datetime | None


class SubscriptionError(RuntimeError):
    """Wraps user-visible problems (bad feed, unresolvable channel, etc.)."""


# ---------------------------------------------------------------------------
# RSS fetch + parse
# ---------------------------------------------------------------------------


async def fetch_channel_feed(
    youtube_channel_id: str,
    *,
    timeout: float = 15.0,
    limit: int = 15,
) -> list[FeedEntry]:
    """Return the most recent entries uploaded by a channel.

    Prefers YouTube's public RSS endpoint (fast, free) but transparently falls
    back to ``yt-dlp``-based channel listing when RSS returns a non-200. This
    resilience matters because YouTube has, at times, silently 404'd the RSS
    endpoint for all channels — an outage we observed 2026-04-20.
    """
    params = {"channel_id": youtube_channel_id}
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.get(RSS_BASE, params=params)
        except httpx.HTTPError as exc:
            logger.info(
                "rss_fetch_network_error_fallback_yt_dlp",
                channel_id=youtube_channel_id,
                error=str(exc),
            )
            return await _yt_dlp_channel_videos(youtube_channel_id, limit=limit)

    if resp.status_code == 200:
        return parse_feed(resp.text)

    logger.info(
        "rss_fetch_http_error_fallback_yt_dlp",
        channel_id=youtube_channel_id,
        status=resp.status_code,
    )
    return await _yt_dlp_channel_videos(youtube_channel_id, limit=limit)


async def _yt_dlp_channel_videos(
    youtube_channel_id: str, *, limit: int = 15
) -> list[FeedEntry]:
    """Fallback: list the channel's most-recent uploads via yt-dlp.

    yt-dlp returns a flat playlist for a ``/channel/<id>/videos`` URL, with
    ids + titles + webpage_urls. Runs in a thread pool to avoid blocking
    the event loop on network I/O.
    """
    import asyncio
    import yt_dlp

    def _extract() -> list[FeedEntry]:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "playlistend": limit,
            "skip_download": True,
        }
        url = f"https://www.youtube.com/channel/{youtube_channel_id}/videos"
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:  # noqa: BLE001
            raise SubscriptionError(f"yt-dlp channel lookup failed: {exc}") from exc
        entries = info.get("entries") or []
        out: list[FeedEntry] = []
        for e in entries:
            vid = e.get("id")
            if not vid:
                continue
            out.append(
                FeedEntry(
                    video_id=vid,
                    title=(e.get("title") or "").strip(),
                    url=e.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}",
                    published_at=None,  # yt-dlp flat listing omits this
                )
            )
        return out

    return await asyncio.to_thread(_extract)


def parse_feed(xml_text: str) -> list[FeedEntry]:
    """Parse YouTube Atom feed XML → entries."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SubscriptionError(f"could not parse RSS XML: {exc}") from exc

    ns = YT_RSS_NAMESPACES
    entries: list[FeedEntry] = []
    for entry in root.findall("atom:entry", ns):
        vid_el = entry.find("yt:videoId", ns)
        title_el = entry.find("atom:title", ns)
        link_el = entry.find("atom:link", ns)
        pub_el = entry.find("atom:published", ns)

        vid = vid_el.text.strip() if vid_el is not None and vid_el.text else None
        if not vid:
            continue
        title = (title_el.text or "").strip() if title_el is not None else ""
        url = link_el.get("href") if link_el is not None else f"https://www.youtube.com/watch?v={vid}"
        published = None
        if pub_el is not None and pub_el.text:
            try:
                published = datetime.fromisoformat(pub_el.text.replace("Z", "+00:00"))
            except ValueError:
                published = None
        entries.append(FeedEntry(video_id=vid, title=title, url=url, published_at=published))
    return entries


def diff_new_videos(entries: list[FeedEntry], seen_ids: list[str]) -> list[FeedEntry]:
    """Return only entries whose video_id is not in ``seen_ids``, preserving order."""
    seen = set(seen_ids or [])
    return [e for e in entries if e.video_id not in seen]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def list_subscriptions(db: AsyncSession) -> list[ChannelSubscription]:
    result = await db.execute(
        select(ChannelSubscription).order_by(ChannelSubscription.created_at.desc())
    )
    return list(result.scalars().all())


async def get_subscription_for_channel(
    db: AsyncSession, channel_id: uuid.UUID
) -> ChannelSubscription | None:
    result = await db.execute(
        select(ChannelSubscription).where(ChannelSubscription.channel_id == channel_id)
    )
    return result.scalar_one_or_none()


async def create_or_enable_subscription(
    db: AsyncSession,
    channel: Channel,
    *,
    poll_frequency_hours: int = 24,
    max_videos_per_poll: int = 3,
) -> ChannelSubscription:
    existing = await get_subscription_for_channel(db, channel.id)
    if existing is not None:
        existing.enabled = True
        existing.disabled_reason = None
        existing.poll_frequency_hours = poll_frequency_hours
        existing.max_videos_per_poll = max_videos_per_poll
        await db.commit()
        await db.refresh(existing)
        return existing
    sub = ChannelSubscription(
        channel_id=channel.id,
        enabled=True,
        poll_frequency_hours=poll_frequency_hours,
        max_videos_per_poll=max_videos_per_poll,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


async def disable_subscription(
    db: AsyncSession, channel_id: uuid.UUID, *, reason: str | None = None
) -> ChannelSubscription | None:
    sub = await get_subscription_for_channel(db, channel_id)
    if sub is None:
        return None
    sub.enabled = False
    if reason:
        sub.disabled_reason = reason
    await db.commit()
    await db.refresh(sub)
    return sub


async def resolve_channel_by_query(db: AsyncSession, query: str) -> Channel | None:
    """Find a channel by name or YouTube handle. Case-insensitive substring."""
    q = query.strip().lower()
    if not q:
        return None
    result = await db.execute(select(Channel))
    channels = list(result.scalars().all())

    # Exact name first, then prefix, then substring.
    for channel in channels:
        if (channel.name or "").lower() == q:
            return channel
    for channel in channels:
        if (channel.name or "").lower().startswith(q):
            return channel
    for channel in channels:
        if q in (channel.name or "").lower():
            return channel
    return None


# ---------------------------------------------------------------------------
# Poll state helpers
# ---------------------------------------------------------------------------


def is_due_for_poll(sub: ChannelSubscription, now: datetime | None = None) -> bool:
    if not sub.enabled:
        return False
    if sub.last_polled_at is None:
        return True
    now = now or datetime.now(timezone.utc)
    delta_hours = (now - sub.last_polled_at).total_seconds() / 3600
    # 30-minute tolerance absorbs cron-scheduler jitter: a daily cron that
    # fires at exactly 02:00 can arrive 0-60s before the 24h boundary and
    # would otherwise silently skip an entire day's poll.
    return delta_hours >= sub.poll_frequency_hours - 0.5


def reset_daily_counter_if_needed(sub: ChannelSubscription) -> None:
    today = datetime.now(timezone.utc).date()
    if sub.daily_counter_reset_at != today:
        sub.videos_ingested_today = 0
        sub.daily_counter_reset_at = today


def mark_poll_success(sub: ChannelSubscription, *, new_ids: list[str]) -> None:
    sub.last_polled_at = datetime.now(timezone.utc)
    sub.consecutive_failure_count = 0
    # Keep last 50 seen ids so the list doesn't grow unbounded.
    merged = list(new_ids) + list(sub.last_seen_video_ids or [])
    sub.last_seen_video_ids = merged[:50]


def mark_poll_failure(sub: ChannelSubscription, *, reason: str, disable_after: int = 3) -> None:
    sub.consecutive_failure_count = (sub.consecutive_failure_count or 0) + 1
    if sub.consecutive_failure_count >= disable_after:
        sub.enabled = False
        sub.disabled_reason = f"Auto-disabled after {sub.consecutive_failure_count} failures: {reason}"


# ---------------------------------------------------------------------------
# Activity touch (drives compression eligibility)
# ---------------------------------------------------------------------------


async def touch_video_activity(db: AsyncSession, video_id: uuid.UUID) -> None:
    """Bump the video's ``last_activity_at`` to now. Silent on missing/errors."""
    from app.models.video import Video

    try:
        video = await db.get(Video, video_id)
        if video is None:
            return
        video.last_activity_at = datetime.now(timezone.utc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("touch_video_activity_failed", video_id=str(video_id), error=str(exc))


def touch_video_activity_sync(db, video_id: uuid.UUID) -> None:
    """Sync version for Celery/Session contexts."""
    from app.models.video import Video

    try:
        video = db.get(Video, video_id)
        if video is None:
            return
        video.last_activity_at = datetime.now(timezone.utc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("touch_video_activity_sync_failed", video_id=str(video_id), error=str(exc))
