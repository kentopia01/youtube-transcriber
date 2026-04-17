"""Weekly digest Celery task.

Produces a Markdown summary of the last 7 days (videos ingested, failures,
personas built, LLM spend) and sends it via ``telegram_notify``. No LLM —
pure stats aggregation.

Invoke via:
  - Manual one-shot:    celery -A app.tasks.celery_app call tasks.weekly_digest
  - CLI:                .venv-native/bin/python -m app.tasks.weekly_digest
  - Cron (recommended): schedule Sundays 18:00 local via OpenClaw cron
                        or launchd, calling the CLI entry above.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.channel import Channel
from app.models.job import Job
from app.models.llm_usage import LlmUsage as LLMUsage
from app.models.persona import Persona
from app.models.video import Video
from app.tasks.celery_app import celery

logger = structlog.get_logger()


def _window_bounds(window_days: int = 7) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=window_days)
    return start, now


def _count(db: Session, stmt) -> int:
    return int(db.execute(stmt).scalar() or 0)


def _sum_cost(db: Session, since: datetime) -> float:
    return float(
        db.execute(
            select(func.coalesce(func.sum(LLMUsage.estimated_cost_usd), 0.0)).where(
                LLMUsage.created_at >= since
            )
        ).scalar()
        or 0.0
    )


def _top_channels_by_new_videos(db: Session, since: datetime, limit: int = 5) -> list[tuple[str, int]]:
    rows = db.execute(
        select(Channel.name, func.count(Video.id).label("n"))
        .join(Video, Video.channel_id == Channel.id)
        .where(Video.created_at >= since)
        .group_by(Channel.id, Channel.name)
        .order_by(text("n DESC"))
        .limit(limit)
    ).all()
    return [(r[0] or "(unknown)", int(r[1])) for r in rows]


def build_digest_text(db: Session, window_days: int = 7) -> dict:
    """Compute the digest and return the payload consumed by telegram_notify."""
    start, now = _window_bounds(window_days)

    videos_ingested = _count(
        db, select(func.count(Video.id)).where(Video.created_at >= start)
    )
    videos_completed = _count(
        db,
        select(func.count(Video.id))
        .where(Video.created_at >= start, Video.status == "completed"),
    )
    videos_failed = _count(
        db,
        select(func.count(Video.id))
        .where(Video.created_at >= start, Video.status == "failed"),
    )
    jobs_failed = _count(
        db,
        select(func.count(Job.id))
        .where(Job.created_at >= start, Job.status == "failed"),
    )
    personas_built = _count(
        db,
        select(func.count(Persona.id))
        .where(Persona.generated_at >= start),
    )
    cost_week = _sum_cost(db, start)
    top_channels = _top_channels_by_new_videos(db, start)

    lines = [
        f"📊 *Weekly digest* ({start.strftime('%b %d')} – {now.strftime('%b %d')})",
        "",
        f"📥 Videos ingested: *{videos_ingested}*"
        + (f" ({videos_completed} completed, {videos_failed} failed)" if videos_ingested else ""),
        f"❌ Jobs failed: *{jobs_failed}*",
        f"✨ Personas built/refreshed: *{personas_built}*",
        f"💰 LLM spend: *${cost_week:.2f}*",
    ]

    if top_channels:
        lines.append("")
        lines.append("*Top channels this week:*")
        for name, n in top_channels:
            lines.append(f"• {name[:50]} — {n}")

    if videos_ingested == 0 and jobs_failed == 0 and personas_built == 0 and cost_week < 0.01:
        lines.append("")
        lines.append("_Quiet week — no activity._")

    return {
        "text": "\n".join(lines),
        "window_start": start.isoformat(),
        "window_end": now.isoformat(),
        "stats": {
            "videos_ingested": videos_ingested,
            "videos_completed": videos_completed,
            "videos_failed": videos_failed,
            "jobs_failed": jobs_failed,
            "personas_built": personas_built,
            "cost_usd": cost_week,
        },
    }


@celery.task(name="tasks.weekly_telegram_digest")
def weekly_telegram_digest() -> dict:
    """Celery task that computes + sends the weekly digest."""
    engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
    try:
        with Session(engine) as db:
            payload = build_digest_text(db)
    finally:
        engine.dispose()

    try:
        from app.services.telegram_notify import notify as _tg_notify

        _tg_notify("digest.weekly", payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("weekly_digest_notify_failed", error=str(exc))

    logger.info("weekly_digest_sent", **payload["stats"])
    return payload["stats"]


def _main() -> None:
    """CLI entry: run and exit. Useful for cron scheduling."""
    result = weekly_telegram_digest()
    print(result)


if __name__ == "__main__":
    _main()
