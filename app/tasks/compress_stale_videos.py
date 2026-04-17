"""Compression sweep — delete on-disk WAVs for videos stale for N days.

Transcript, summary, and embeddings stay in Postgres, so chat with a
compressed video still works. The raw audio can be re-downloaded via
yt-dlp on demand if a re-process is ever needed.

Invocation (pick one):
  - Celery:  ``celery -A app.tasks.celery_app call tasks.compress_stale_videos``
  - CLI:     ``python -m app.tasks.compress_stale_videos``  (wire to cron)
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.video import Video
from app.tasks.celery_app import celery

logger = structlog.get_logger()


def _resolve_wav_path(video: Video) -> Path | None:
    """Return the WAV path for this video if it's obtainable; else None."""
    if video.audio_file_path:
        # Strip leading './' or similar relatives
        return Path(video.audio_file_path)
    return Path(settings.audio_dir) / f"{video.youtube_video_id}.wav"


def _compress_one(db: Session, video: Video) -> dict[str, Any]:
    """Try to compress a single video's WAV. Always marks compressed_at."""
    result = {
        "video_id": str(video.id),
        "wav_deleted": False,
        "bytes_reclaimed": 0,
        "note": None,
    }
    path = _resolve_wav_path(video)
    if path and path.exists():
        try:
            size = path.stat().st_size
            path.unlink()
            result["wav_deleted"] = True
            result["bytes_reclaimed"] = size
        except Exception as exc:  # noqa: BLE001
            logger.warning("compress_unlink_failed", video_id=str(video.id), path=str(path), error=str(exc))
            result["note"] = f"unlink_failed: {exc}"
    else:
        result["note"] = "wav_already_absent"

    video.compressed_at = datetime.now(timezone.utc)
    return result


def compress_stale_videos_once(stale_days: int | None = None) -> dict[str, Any]:
    """Core compression logic. Returns stats."""
    stale_days = stale_days if stale_days is not None else settings.compression_stale_days

    engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
    cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)

    processed = 0
    reclaimed = 0
    per_video: list[dict[str, Any]] = []

    try:
        with Session(engine) as db:
            stmt = (
                select(Video)
                .where(
                    Video.status == "completed",
                    Video.compressed_at.is_(None),
                    or_(Video.last_activity_at.is_(None), Video.last_activity_at < cutoff),
                )
                .order_by(Video.id)
                .limit(200)  # safety bound per run
            )
            candidates = db.execute(stmt).scalars().all()
            for video in candidates:
                res = _compress_one(db, video)
                per_video.append(res)
                processed += 1
                reclaimed += int(res.get("bytes_reclaimed") or 0)
            db.commit()
    finally:
        engine.dispose()

    logger.info(
        "compress_stale_videos_done",
        processed=processed,
        reclaimed_mb=round(reclaimed / (1024 * 1024), 2),
        stale_days=stale_days,
    )
    return {
        "processed": processed,
        "bytes_reclaimed": reclaimed,
        "stale_days": stale_days,
        "per_video": per_video,
    }


@celery.task(name="tasks.compress_stale_videos")
def compress_stale_videos() -> dict[str, Any]:
    if not settings.compression_enabled:
        logger.info("compress_stale_videos_disabled")
        return {"processed": 0, "bytes_reclaimed": 0, "skipped": "disabled"}
    return compress_stale_videos_once()


def _main() -> None:
    result = compress_stale_videos()
    print(result)


if __name__ == "__main__":
    _main()
