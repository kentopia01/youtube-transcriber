"""Celery task: generate a channel persona.

Runs on the `post` queue (same as summarize/embed). Idempotent and
self-gating — it re-checks `channel_needs_persona` at start, so multiple
enqueues for the same channel are safe and cheap.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.channel import Channel
from app.services.persona import (
    SCOPE_CHANNEL,
    channel_needs_persona,
    count_completed_videos,
    derive_persona,
    select_characteristic_chunks,
    upsert_persona,
)
from app.tasks.celery_app import celery

logger = structlog.get_logger()


async def _run(channel_id: str, forced: bool) -> dict[str, Any]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as db:
            channel_uuid = uuid.UUID(channel_id)
            channel = await db.get(Channel, channel_uuid)
            if channel is None:
                raise ValueError(f"channel {channel_id} not found")

            if not forced:
                should, reason = await channel_needs_persona(db, channel_uuid)
                if not should:
                    logger.info(
                        "channel_persona_skip", channel_id=channel_id, reason=reason
                    )
                    return {"status": "skipped", "reason": reason}

            # Capture whether this is the channel's first persona so we can
            # emit the right notification event after upsert.
            from app.services.persona import get_persona as _get_persona

            existing_persona = await _get_persona(db, SCOPE_CHANNEL, str(channel_uuid))
            was_refresh = existing_persona is not None

            chunks = await select_characteristic_chunks(db, channel_uuid)
            if not chunks:
                logger.warning(
                    "channel_persona_no_chunks", channel_id=channel_id, channel_name=channel.name
                )
                return {"status": "skipped", "reason": "no embedding chunks"}

            derivation = derive_persona(
                channel_name=channel.name,
                channel_description=channel.description,
                chunks=chunks,
            )

            completed = await count_completed_videos(db, channel_uuid)
            persona = await upsert_persona(
                db,
                derivation,
                scope_type=SCOPE_CHANNEL,
                scope_id=str(channel_uuid),
                videos_at_generation=completed,
            )

            try:
                from app.services.telegram_notify import notify as _tg_notify

                event = "persona.refreshed" if was_refresh else "persona.generated"
                _tg_notify(
                    event,
                    {
                        "display_name": persona.display_name,
                        "confidence": float(persona.confidence),
                        "channel_id": str(channel_uuid),
                        "is_refresh": was_refresh,
                    },
                )
            except Exception:  # noqa: BLE001
                pass

            return {
                "status": "generated",
                "persona_id": str(persona.id),
                "display_name": persona.display_name,
                "confidence": persona.confidence,
                "source_chunk_count": persona.source_chunk_count,
                "videos_at_generation": persona.videos_at_generation,
            }
    finally:
        await engine.dispose()


@celery.task(
    bind=True,
    name="tasks.generate_channel_persona",
    max_retries=2,
    default_retry_delay=60,
)
def generate_channel_persona_task(
    self, channel_id: str, forced: bool = False
) -> dict[str, Any]:
    logger.info("channel_persona_task_start", channel_id=channel_id, forced=forced)
    try:
        result = asyncio.run(_run(channel_id, forced))
        logger.info(
            "channel_persona_task_done", channel_id=channel_id, status=result.get("status")
        )
        return result
    except Exception as exc:
        logger.warning(
            "channel_persona_task_error",
            channel_id=channel_id,
            error=str(exc),
            retries=self.request.retries,
        )
        raise self.retry(exc=exc)


def enqueue_channel_persona(channel_id: str, *, forced: bool = False) -> None:
    """Fire-and-forget enqueue. Errors are logged, never raised to the caller
    (we never want to fail an upstream pipeline task because persona enqueueing
    hiccupped)."""
    try:
        generate_channel_persona_task.apply_async(
            args=[str(channel_id)],
            kwargs={"forced": forced},
            queue="post",
        )
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("channel_persona_enqueue_failed", channel_id=channel_id, error=str(exc))
