"""Reconcile videos whose status is stuck in a non-terminal pipeline stage.

The stale-job reaper marks Job rows as failed when they hang in a stage past
the timeout, but ``Video.status`` isn't always reset — especially when the
reaper fires between stage transitions. This task walks any videos parked
in an intermediate status (``downloaded``, ``transcribed``, ``diarized``,
``cleaned``, ``summarized``) that have no currently active Job, and marks
them ``failed`` so they re-enter the normal retry flow.

Invocation (pick one):
  - Celery:  ``celery -A app.tasks.celery_app call tasks.reconcile_video_status``
  - CLI:     ``python -m app.tasks.reconcile_video_status``
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import settings
from app.tasks.celery_app import celery

logger = structlog.get_logger()


# Statuses that represent "the pipeline ran partway but didn't finish."
# ``pending`` is not included because a freshly-submitted video with no job
# yet is a legitimate pending state; leave it alone.
NON_TERMINAL_VIDEO_STATUSES = (
    "downloaded",
    "transcribed",
    "diarized",
    "cleaned",
    "summarized",
)


def _find_and_reconcile(db: Session, *, quiet_for_minutes: int) -> list[dict[str, Any]]:
    """Return the list of reconciled rows, after updating them."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=quiet_for_minutes)

    # Videos in a non-terminal status whose most-recent job is NOT active and
    # whose last update is older than the cutoff. The cutoff prevents us from
    # reaping a video that's moving between stages right now.
    sql = text(
        """
        WITH active_jobs AS (
            SELECT DISTINCT video_id
            FROM jobs
            WHERE status IN ('pending', 'queued', 'running')
        )
        SELECT v.id, v.title, v.status, v.updated_at
        FROM videos v
        WHERE v.status = ANY(:non_terminal)
          AND v.id NOT IN (SELECT video_id FROM active_jobs)
          AND (v.updated_at IS NULL OR v.updated_at < :cutoff)
        ORDER BY v.updated_at NULLS FIRST
        LIMIT 100
        """
    )

    rows = db.execute(
        sql,
        {
            "non_terminal": list(NON_TERMINAL_VIDEO_STATUSES),
            "cutoff": cutoff,
        },
    ).fetchall()

    reconciled: list[dict[str, Any]] = []
    for row in rows:
        reason = f"Reconciled: stuck in '{row.status}' with no active job"
        db.execute(
            text(
                "UPDATE videos SET status = 'failed', error_message = :reason "
                "WHERE id = :vid"
            ),
            {"reason": reason, "vid": row.id},
        )
        reconciled.append({
            "video_id": str(row.id),
            "title": row.title,
            "previous_status": row.status,
        })
    db.commit()
    return reconciled


def reconcile_once(quiet_for_minutes: int | None = None) -> dict[str, Any]:
    """Top-level entry — opens its own session, commits, returns stats."""
    # Require at least the queued-timeout of quiet before we call a video stuck;
    # prevents racing with a pipeline stage transition mid-execution.
    quiet_for_minutes = (
        quiet_for_minutes
        if quiet_for_minutes is not None
        else settings.pipeline_stale_timeout_queued_minutes
    )

    engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
    try:
        with Session(engine) as db:
            reconciled = _find_and_reconcile(db, quiet_for_minutes=quiet_for_minutes)
    finally:
        engine.dispose()

    logger.info(
        "reconcile_video_status_done",
        reconciled=len(reconciled),
        quiet_for_minutes=quiet_for_minutes,
    )
    return {
        "reconciled": len(reconciled),
        "quiet_for_minutes": quiet_for_minutes,
        "rows": reconciled,
    }


@celery.task(name="tasks.reconcile_video_status")
def reconcile_video_status() -> dict[str, Any]:
    return reconcile_once()


def _main() -> None:
    result = reconcile_once()
    print(result)


if __name__ == "__main__":
    _main()
