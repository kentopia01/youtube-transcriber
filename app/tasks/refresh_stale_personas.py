"""Daily sweep: refresh any channel persona whose channel has gained new
completed videos since the persona was last generated.

This replaces the old counter-based approach (``persona.refresh_after_videos``)
which could drift when auto-ingest was spotty. The new mechanism is purely
time-based: if any video in the channel was completed after
``persona.generated_at``, enqueue a refresh.

Invocation:
  - Celery:  ``celery -A app.tasks.celery_app call tasks.refresh_stale_personas``
  - CLI:     ``python -m app.tasks.refresh_stale_personas``
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.persona import Persona
from app.models.video import Video
from app.services.persona import SCOPE_CHANNEL
from app.tasks.celery_app import celery
from app.tasks.generate_persona import enqueue_channel_persona

logger = structlog.get_logger()


def _new_completions_since(db: Session, channel_id: uuid.UUID, since) -> int:
    return int(
        db.execute(
            select(func.count(Video.id)).where(
                Video.channel_id == channel_id,
                Video.status == "completed",
                Video.created_at > since,
            )
        ).scalar()
        or 0
    )


def run_refresh_sweep() -> dict[str, Any]:
    engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
    queued: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    try:
        with Session(engine) as db:
            personas = db.execute(
                select(Persona).where(Persona.scope_type == SCOPE_CHANNEL)
            ).scalars().all()

            for persona in personas:
                try:
                    channel_uuid = uuid.UUID(persona.scope_id)
                except ValueError:
                    logger.warning(
                        "refresh_sweep_bad_scope_id",
                        persona_id=str(persona.id),
                        scope_id=persona.scope_id,
                    )
                    continue

                new = _new_completions_since(db, channel_uuid, persona.generated_at)
                entry = {
                    "channel_id": str(channel_uuid),
                    "display_name": persona.display_name,
                    "new_completions": new,
                }
                if new > 0:
                    enqueue_channel_persona(str(channel_uuid), forced=True)
                    queued.append(entry)
                else:
                    skipped.append(entry)
    finally:
        engine.dispose()

    logger.info(
        "refresh_stale_personas_done",
        queued=len(queued),
        skipped=len(skipped),
    )
    return {"queued": len(queued), "skipped": len(skipped), "details_queued": queued}


@celery.task(name="tasks.refresh_stale_personas")
def refresh_stale_personas() -> dict[str, Any]:
    return run_refresh_sweep()


def _main() -> None:
    result = refresh_stale_personas()
    print(result)


if __name__ == "__main__":
    _main()
