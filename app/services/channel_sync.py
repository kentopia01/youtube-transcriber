from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.video import Video


def parse_upload_date(value: str | None) -> datetime | None:
    """Parse yt-dlp upload dates (YYYYMMDD) into UTC datetimes."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def build_channel_url(
    youtube_channel_id: str,
    channel_name: str | None = None,
    channel_url: str | None = None,
) -> str:
    """Choose the best available canonical URL for a YouTube channel."""
    if channel_url:
        return channel_url
    if channel_name:
        handleish = channel_name.strip().replace(" ", "")
        if handleish:
            return f"https://www.youtube.com/@{handleish}"
    return f"https://www.youtube.com/channel/{youtube_channel_id}"


async def get_or_create_channel(
    db: AsyncSession,
    *,
    youtube_channel_id: str | None,
    name: str | None,
    url: str | None = None,
    description: str | None = None,
    thumbnail_url: str | None = None,
    last_synced_at: datetime | None = None,
) -> Channel | None:
    """Upsert a channel from fetched metadata."""
    if not youtube_channel_id:
        return None

    result = await db.execute(
        select(Channel).where(Channel.youtube_channel_id == youtube_channel_id)
    )
    channel = result.scalar_one_or_none()
    resolved_name = name or youtube_channel_id
    resolved_url = build_channel_url(youtube_channel_id, resolved_name, url)

    if not channel:
        channel = Channel(
            youtube_channel_id=youtube_channel_id,
            name=resolved_name,
            url=resolved_url,
            description=description,
            thumbnail_url=thumbnail_url,
            last_synced_at=last_synced_at,
        )
        db.add(channel)
        await db.flush()
        return channel

    channel.name = resolved_name
    channel.url = resolved_url
    if description:
        channel.description = description
    if thumbnail_url:
        channel.thumbnail_url = thumbnail_url
    if last_synced_at is not None:
        channel.last_synced_at = last_synced_at
    return channel


async def sync_discovered_videos(
    db: AsyncSession,
    channel: Channel,
    videos: list[dict],
) -> int:
    """Upsert discovered channel videos so the library can render them immediately."""
    channel_chat_enabled = True if channel.chat_enabled is None else channel.chat_enabled
    synced = 0

    for item in videos:
        yt_video_id = (item.get("video_id") or "").strip()
        if not yt_video_id:
            continue

        published_at = parse_upload_date(item.get("published_at"))
        video_url = item.get("url") or f"https://www.youtube.com/watch?v={yt_video_id}"

        existing = await db.execute(
            select(Video).where(Video.youtube_video_id == yt_video_id)
        )
        video = existing.scalar_one_or_none()

        if not video:
            video = Video(
                youtube_video_id=yt_video_id,
                channel_id=channel.id,
                title=item.get("title") or "Untitled",
                url=video_url,
                duration_seconds=item.get("duration"),
                published_at=published_at,
                thumbnail_url=item.get("thumbnail"),
                status="discovered",
                chat_enabled=channel_chat_enabled,
            )
            db.add(video)
            synced += 1
            continue

        video.channel_id = channel.id
        if item.get("title"):
            video.title = item["title"]
        video.url = video_url
        if item.get("duration") is not None:
            video.duration_seconds = item["duration"]
        if published_at is not None:
            video.published_at = published_at
        if item.get("thumbnail"):
            video.thumbnail_url = item["thumbnail"]
        synced += 1

    return synced


async def refresh_channel_video_count(db: AsyncSession, channel: Channel) -> None:
    """Set channel.video_count to the number of linked videos currently stored."""
    total = await db.scalar(
        select(func.count(Video.id)).where(Video.channel_id == channel.id)
    )
    channel.video_count = int(total or 0)
