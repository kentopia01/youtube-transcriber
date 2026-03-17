#!/usr/bin/env python3
"""Audit and backfill channel/video links for the existing library.

Usage:
  python scripts/backfill_channels.py
  python scripts/backfill_channels.py --apply
  python scripts/backfill_channels.py --apply --limit 10
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session

sys.path.insert(0, ".")

from app.models.channel import Channel
from app.models.video import Video
from app.services.channel_sync import build_channel_url, parse_upload_date
from app.services.youtube import get_video_info


DEFAULT_DB_URL = "postgresql+psycopg2://transcriber:transcriber@localhost:5432/transcriber"


@dataclass
class AuditSummary:
    videos_total: int
    channels_total: int
    videos_with_channel_id: int
    videos_missing_channel_id: int
    channels_with_zero_videos: int


def audit_summary(db: Session) -> AuditSummary:
    videos_total = db.query(func.count(Video.id)).scalar() or 0
    channels_total = db.query(func.count(Channel.id)).scalar() or 0
    videos_with_channel_id = db.query(func.count(Video.id)).filter(Video.channel_id.isnot(None)).scalar() or 0
    videos_missing_channel_id = videos_total - videos_with_channel_id
    channels_with_zero_videos = (
        db.query(func.count(Channel.id))
        .outerjoin(Video, Video.channel_id == Channel.id)
        .group_by(Channel.id)
        .having(func.count(Video.id) == 0)
        .count()
    )
    return AuditSummary(
        videos_total=int(videos_total),
        channels_total=int(channels_total),
        videos_with_channel_id=int(videos_with_channel_id),
        videos_missing_channel_id=int(videos_missing_channel_id),
        channels_with_zero_videos=int(channels_with_zero_videos),
    )


def print_summary(label: str, summary: AuditSummary) -> None:
    print(f"\n{label}")
    print(f"  videos_total: {summary.videos_total}")
    print(f"  channels_total: {summary.channels_total}")
    print(f"  videos_with_channel_id: {summary.videos_with_channel_id}")
    print(f"  videos_missing_channel_id: {summary.videos_missing_channel_id}")
    print(f"  channels_with_zero_videos: {summary.channels_with_zero_videos}")


def print_unlinked_sample(db: Session, limit: int = 10) -> None:
    rows = (
        db.query(Video.youtube_video_id, Video.title)
        .filter(Video.channel_id.is_(None))
        .order_by(Video.created_at.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        print("\nNo unlinked videos found.")
        return

    print(f"\nSample unlinked videos ({len(rows)} shown):")
    for youtube_video_id, title in rows:
        print(f"  {youtube_video_id}  {title[:100]}")


def get_or_create_channel(db: Session, info: dict) -> Channel | None:
    youtube_channel_id = info.get("channel_id")
    if not youtube_channel_id:
        return None

    name = info.get("channel_name") or youtube_channel_id
    url = build_channel_url(
        youtube_channel_id,
        name,
        info.get("channel_url"),
    )

    channel = (
        db.query(Channel)
        .filter(Channel.youtube_channel_id == youtube_channel_id)
        .first()
    )
    if not channel:
        channel = Channel(
            youtube_channel_id=youtube_channel_id,
            name=name,
            url=url,
            last_synced_at=datetime.now(UTC),
        )
        db.add(channel)
        db.flush()
        return channel

    channel.name = name
    channel.url = url
    channel.last_synced_at = datetime.now(UTC)
    return channel


def refresh_channel_counts(db: Session) -> None:
    channels = db.query(Channel).all()
    for channel in channels:
        linked_total = (
            db.query(func.count(Video.id))
            .filter(Video.channel_id == channel.id)
            .scalar()
            or 0
        )
        channel.video_count = int(linked_total)


def backfill(db: Session, limit: int | None = None) -> tuple[int, int]:
    query = (
        db.query(Video)
        .filter(Video.channel_id.is_(None))
        .order_by(Video.created_at.desc())
    )
    if limit is not None:
        query = query.limit(limit)

    videos = query.all()
    linked = 0
    failed = 0

    for idx, video in enumerate(videos, 1):
        try:
            info = get_video_info(f"https://www.youtube.com/watch?v={video.youtube_video_id}")
            channel = get_or_create_channel(db, info)
            if channel:
                video.channel_id = channel.id
                linked += 1

            video.title = info.get("title", video.title)
            video.description = info.get("description", video.description)
            video.url = info.get("url", video.url)
            video.duration_seconds = info.get("duration", video.duration_seconds)
            video.thumbnail_url = info.get("thumbnail", video.thumbnail_url)
            video.published_at = parse_upload_date(info.get("published_at")) or video.published_at

            print(f"  [{idx}/{len(videos)}] linked {video.youtube_video_id} -> {info.get('channel_name') or info.get('channel_id')}")
        except Exception as exc:
            failed += 1
            print(f"  [{idx}/{len(videos)}] FAILED {video.youtube_video_id}: {exc}")

    refresh_channel_counts(db)
    return linked, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and backfill video/channel links")
    parser.add_argument("--apply", action="store_true", help="Write backfilled channel links to the database")
    parser.add_argument("--limit", type=int, help="Only inspect/backfill the newest N unlinked videos")
    parser.add_argument("--db-url", default=DEFAULT_DB_URL, help="SQLAlchemy sync Postgres URL")
    args = parser.parse_args()

    engine = create_engine(args.db_url)

    with Session(engine) as db:
        before = audit_summary(db)
        print_summary("Before", before)
        print_unlinked_sample(db, limit=min(args.limit or 10, 10))

        if not args.apply:
            print("\nAudit only. Re-run with --apply to backfill missing channel links.")
            return 0

        linked, failed = backfill(db, limit=args.limit)
        db.commit()

        after = audit_summary(db)
        print_summary("After", after)
        print(f"\nBackfill complete: linked={linked}, failed={failed}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
