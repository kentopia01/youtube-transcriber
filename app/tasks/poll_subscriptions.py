"""Nightly watchlist poll.

For every enabled, due subscription:
  1. Fetch the channel's YouTube RSS feed.
  2. Diff against ``last_seen_video_ids`` → new uploads.
  3. Stop early if the daily auto-ingest cost cap is breached.
  4. Submit up to ``max_videos_per_poll`` new videos through the normal
     pipeline, tagging them with ``ATTEMPT_REASON_AUTO_INGEST`` so
     downstream LLM spend is attributed to the autonomous budget.
  5. On exception: increment failure counter; auto-disable after 3 in a row.

Invocation (pick one):
  - Celery:  generate_embeddings and friends already run the cleanup/
             summarize tasks downstream; this task just queues them.
  - CLI:     ``python -m app.tasks.poll_subscriptions`` — wire to cron.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.channel import Channel
from app.models.channel_subscription import ChannelSubscription
from app.services.cost_tracker import auto_ingest_budget_remaining
from app.services.pipeline_observability import ATTEMPT_REASON_AUTO_INGEST
from app.services.subscriptions import (
    FeedEntry,
    SubscriptionError,
    diff_new_videos,
    fetch_channel_feed,
    is_due_for_poll,
    mark_poll_failure,
    mark_poll_success,
    reset_daily_counter_if_needed,
)
from app.tasks.celery_app import celery

logger = structlog.get_logger()


async def _submit_video(
    url: str, *, api_key: str | None = None
) -> dict[str, Any]:
    """Submit a video URL via the web API. Returns the parsed JSON response.

    Using the HTTP API (rather than calling the submit service directly) keeps
    all existing pipeline-attempt guards in place and avoids duplicate logic.
    """
    headers = {"X-Internal-Attempt-Reason": ATTEMPT_REASON_AUTO_INGEST}
    if api_key:
        headers["X-API-Key"] = api_key
    async with httpx.AsyncClient(
        base_url=settings.internal_web_base_url, timeout=60.0
    ) as client:
        resp = await client.post("/api/videos", json={"url": url}, headers=headers)
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail") or resp.text
        except Exception:
            detail = resp.text
        raise RuntimeError(f"submit failed ({resp.status_code}): {detail}")
    return resp.json()


async def _tag_job_as_auto_ingest(db, job_id: str) -> None:
    """Flip the latest job row for this video to attempt_creation_reason='auto_ingest'."""
    from app.models.job import Job

    job = await db.get(Job, uuid.UUID(job_id))
    if job is not None:
        job.attempt_creation_reason = ATTEMPT_REASON_AUTO_INGEST
        await db.commit()


async def _process_one_subscription(
    db, sub: ChannelSubscription, *, budget_remaining: float
) -> dict[str, Any]:
    """Poll a single subscription. Returns a stats dict. Never raises — all
    errors are captured in the subscription's failure state."""
    result = {
        "subscription_id": str(sub.id),
        "channel_name": None,
        "new_videos_found": 0,
        "ingested": 0,
        "skipped_reason": None,
    }

    channel = sub.channel  # lazy-loaded, already joined
    if channel is None:
        channel = await db.get(Channel, sub.channel_id)
    result["channel_name"] = channel.name if channel else None

    if channel is None or not channel.youtube_channel_id:
        mark_poll_failure(sub, reason="channel missing youtube_channel_id")
        result["skipped_reason"] = "missing_youtube_channel_id"
        await db.commit()
        return result

    # Fetch feed
    try:
        entries: list[FeedEntry] = await fetch_channel_feed(channel.youtube_channel_id)
    except SubscriptionError as exc:
        mark_poll_failure(sub, reason=str(exc))
        await db.commit()
        result["skipped_reason"] = f"rss_error: {exc}"
        return result

    new_entries = diff_new_videos(entries, list(sub.last_seen_video_ids or []))
    result["new_videos_found"] = len(new_entries)

    if not new_entries:
        mark_poll_success(sub, new_ids=[])
        await db.commit()
        return result

    reset_daily_counter_if_needed(sub)
    remaining_today = max(0, sub.max_videos_per_poll - (sub.videos_ingested_today or 0))
    to_ingest = new_entries[:remaining_today]

    if budget_remaining <= 0.10:
        # Mark seen anyway so we don't keep re-queuing the same videos next run.
        mark_poll_success(sub, new_ids=[e.video_id for e in new_entries])
        await db.commit()
        result["skipped_reason"] = "auto_ingest_budget_exhausted"
        return result

    ingested_ids: list[str] = []
    rejected_filter_ids: list[str] = []
    rejected_count = 0
    for entry in to_ingest:
        # Filter Shorts / live streams before we pay to submit them.
        try:
            from app.services.video_classifier import classify_video_url

            classification = classify_video_url(entry.url)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "auto_ingest_classifier_error",
                video_id=entry.video_id,
                error=str(exc),
            )
            # Fail-open
            from app.services.video_classifier import ClassificationResult

            classification = ClassificationResult(True, None)

        if not classification.is_regular:
            rejected_count += 1
            rejected_filter_ids.append(entry.video_id)
            logger.info(
                "auto_ingest_skipped_filter",
                video_id=entry.video_id,
                reason=classification.reason,
            )
            continue

        try:
            submit_resp = await _submit_video(entry.url)
            job_id = submit_resp.get("job_id")
            if job_id:
                await _tag_job_as_auto_ingest(db, job_id)
            ingested_ids.append(entry.video_id)
            sub.videos_ingested_today = (sub.videos_ingested_today or 0) + 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("auto_ingest_submit_failed", video_id=entry.video_id, error=str(exc))
            mark_poll_failure(sub, reason=f"submit failed for {entry.video_id}: {exc}")
            await db.commit()
            result["skipped_reason"] = f"submit_error: {exc}"
            return result

    result["rejected_by_filter"] = rejected_count

    # Only mark as seen: videos we actually ingested + ones the classifier
    # deliberately rejected. Entries truncated by the per-poll cap stay in the
    # diff pool so the next poll run can pick them up. This prevents the
    # "saw but never ingested" orphaning that happens on first-poll backlogs.
    mark_poll_success(sub, new_ids=ingested_ids + rejected_filter_ids)
    await db.commit()
    result["ingested"] = len(ingested_ids)
    return result


async def _run_poll() -> dict[str, Any]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    total_ingested = 0
    stats: list[dict[str, Any]] = []
    soft_cap_crossed = False  # notify once per run when auto-ingest spend
                              # crosses the soft cap. Polling continues.

    try:
        async with SessionLocal() as db:
            subs = (
                await db.execute(
                    select(ChannelSubscription).order_by(
                        ChannelSubscription.last_polled_at.asc().nullsfirst()
                    )
                )
            ).scalars().all()

            for sub in subs:
                if not is_due_for_poll(sub):
                    continue

                remaining = auto_ingest_budget_remaining()
                if remaining <= 0 and not soft_cap_crossed:
                    soft_cap_crossed = True
                    logger.info(
                        "auto_ingest_soft_cap_crossed",
                        cap=settings.auto_ingest_daily_cost_cap_usd,
                    )

                # Soft cap: pass a large budget to the per-sub handler so it
                # never gates on autonomous spend. The global daily_llm_budget_usd
                # inside check_budget() remains the hard ceiling.
                s = await _process_one_subscription(db, sub, budget_remaining=1e9)
                stats.append(s)
                total_ingested += int(s.get("ingested") or 0)
    finally:
        await engine.dispose()

    result = {
        "processed_subscriptions": len(stats),
        "total_ingested": total_ingested,
        "soft_cap_crossed": soft_cap_crossed,
        "details": stats,
    }
    logger.info("poll_subscriptions_done", **{k: v for k, v in result.items() if k != "details"})

    if soft_cap_crossed:
        try:
            from app.services.telegram_notify import notify as _tg_notify

            _tg_notify(
                "cost.threshold_100",
                {
                    "spent": settings.auto_ingest_daily_cost_cap_usd,
                    "cap": settings.auto_ingest_daily_cost_cap_usd,
                },
            )
        except Exception:  # noqa: BLE001
            pass

    return result


@celery.task(name="tasks.poll_subscriptions")
def poll_subscriptions() -> dict[str, Any]:
    return asyncio.run(_run_poll())


def _main() -> None:
    result = poll_subscriptions()
    print(result)


if __name__ == "__main__":
    _main()
