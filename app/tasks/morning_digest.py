"""Morning digest — Chief-of-Staff brief of last 24h activity, delivered
via Telegram at 08:00 local.

Invocation:
  - Celery:  celery -A app.tasks.celery_app call tasks.morning_digest
  - CLI:     python -m app.tasks.morning_digest
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.services.digest import gather_digest_inputs, render_digest_via_llm
from app.tasks.celery_app import celery

logger = structlog.get_logger()


def run_morning_digest(window_hours: int = 24) -> dict[str, Any]:
    engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
    try:
        with Session(engine) as db:
            inputs = gather_digest_inputs(db, window_hours=window_hours)
    finally:
        engine.dispose()

    if (
        not inputs.videos_completed
        and not inputs.videos_failed
        and not inputs.personas_touched
    ):
        # Still render — the system prompt tells the LLM to produce a minimal
        # brief when there's nothing. This costs ~$0.005 and keeps the
        # cadence consistent even on quiet nights.
        logger.info("morning_digest_quiet_window")

    result = render_digest_via_llm(inputs)

    try:
        from app.services.telegram_notify import notify as _tg_notify

        _tg_notify(
            "digest.morning",
            {
                "text": result["text"],
                "window_start": result["window_start"],
                "window_end": result["window_end"],
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("morning_digest_notify_failed", error=str(exc))

    logger.info(
        "morning_digest_sent",
        videos_completed=len(inputs.videos_completed),
        videos_failed=len(inputs.videos_failed),
        prompt_tokens=result["prompt_tokens"],
        completion_tokens=result["completion_tokens"],
    )
    return {
        "videos_completed": len(inputs.videos_completed),
        "videos_failed": len(inputs.videos_failed),
        "personas_touched": len(inputs.personas_touched),
        "cost_auto_ingest_usd": inputs.cost_auto_ingest_usd,
        "cost_manual_usd": inputs.cost_manual_usd,
        "prompt_tokens": result["prompt_tokens"],
        "completion_tokens": result["completion_tokens"],
    }


@celery.task(name="tasks.morning_digest")
def morning_digest() -> dict[str, Any]:
    return run_morning_digest()


def _main() -> None:
    print(morning_digest())


if __name__ == "__main__":
    _main()
