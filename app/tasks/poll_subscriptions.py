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
from app.models.job import Job, PIPELINE_ACTIVE_STATUSES
from app.models.lane_subscription import LaneSubscription
from app.models.lane_video_item import LaneVideoItem
from app.models.video import Video
from app.services.cost_tracker import auto_ingest_budget_remaining
from app.services.download_circuit import circuit_state_payload, get_download_circuit_state
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


class VideoSubmissionError(RuntimeError):
    """Structured failure returned by the local video-submission API."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"submit failed ({status_code}): {detail}")


class ManualReviewSubmissionBlocked(VideoSubmissionError):
    """The video is already contained and requires explicit operator review."""


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
        detail = str(detail)
        if resp.status_code == 409 and "manual review" in detail.lower():
            raise ManualReviewSubmissionBlocked(resp.status_code, detail)
        raise VideoSubmissionError(resp.status_code, detail)
    return resp.json()


async def _tag_job_as_auto_ingest(db, job_id: str) -> None:
    """Flip the latest job row for this video to attempt_creation_reason='auto_ingest'."""
    from app.models.job import Job

    job = await db.get(Job, uuid.UUID(job_id))
    if job is not None:
        job.attempt_creation_reason = ATTEMPT_REASON_AUTO_INGEST
        await db.commit()


async def _process_one_subscription(
    db,
    sub: ChannelSubscription,
    *,
    budget_remaining: float,
    submission_limit: int | None = None,
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
    allowed = remaining_today
    if submission_limit is not None:
        allowed = min(allowed, max(0, submission_limit))
    to_ingest = new_entries[:allowed]

    if allowed <= 0:
        result["skipped_reason"] = "global_submission_cap_reached"
        return result

    if budget_remaining <= 0.10:
        # Mark seen anyway so we don't keep re-queuing the same videos next run.
        mark_poll_success(sub, new_ids=[e.video_id for e in new_entries])
        await db.commit()
        result["skipped_reason"] = "auto_ingest_budget_exhausted"
        return result

    ingested_ids: list[str] = []
    rejected_filter_ids: list[str] = []
    manual_review_ids: list[str] = []
    rejected_count = 0
    deferred_count = 0
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
            if classification.retry_later:
                deferred_count += 1
            else:
                rejected_count += 1
                rejected_filter_ids.append(entry.video_id)
            logger.info(
                "auto_ingest_deferred" if classification.retry_later else "auto_ingest_skipped_filter",
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
        except ManualReviewSubmissionBlocked as exc:
            manual_review_ids.append(entry.video_id)
            logger.info(
                "auto_ingest_manual_review_preserved",
                video_id=entry.video_id,
                status_code=exc.status_code,
                outcome="marked_seen_without_subscription_failure",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("auto_ingest_submit_failed", video_id=entry.video_id, error=str(exc))
            mark_poll_failure(sub, reason=f"submit failed for {entry.video_id}: {exc}")
            await db.commit()
            result["skipped_reason"] = f"submit_error: {exc}"
            return result

    result["rejected_by_filter"] = rejected_count
    result["deferred_for_retry"] = deferred_count
    result["manual_review_blocked"] = len(manual_review_ids)

    # Only mark as seen: videos we actually ingested + ones the classifier
    # deliberately rejected. Entries truncated by the per-poll cap stay in the
    # diff pool so the next poll run can pick them up. This prevents the
    # "saw but never ingested" orphaning that happens on first-poll backlogs.
    mark_poll_success(
        sub,
        new_ids=ingested_ids + rejected_filter_ids + manual_review_ids,
    )
    await db.commit()
    result["ingested"] = len(ingested_ids)
    return result


async def _attach_or_submit_lane_entry(
    db,
    sub: LaneSubscription,
    entry: FeedEntry,
) -> str:
    """Attach shared work to a lane, submitting only when no reusable work exists."""
    existing_item = (
        await db.execute(
            select(LaneVideoItem).where(
                LaneVideoItem.lane_id == sub.lane_id,
                LaneVideoItem.video_id
                == select(Video.id)
                .where(Video.youtube_video_id == entry.video_id)
                .scalar_subquery(),
            )
        )
    ).scalar_one_or_none()
    if existing_item is not None:
        return "already_attached"

    video = (
        await db.execute(
            select(Video).where(Video.youtube_video_id == entry.video_id)
        )
    ).scalar_one_or_none()
    active_job = None
    if video is not None:
        active_job = (
            await db.execute(
                select(Job)
                .where(
                    Job.video_id == video.id,
                    Job.job_type == "pipeline",
                    Job.status.in_(PIPELINE_ACTIVE_STATUSES),
                )
                .order_by(Job.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    if video is not None and (video.status == "completed" or active_job is not None):
        item = LaneVideoItem(
            lane_id=sub.lane_id,
            video_id=video.id,
            lane_subscription_id=sub.id,
            processing_job_id=active_job.id if active_job is not None else None,
            source="lane_poll",
        )
        db.add(item)
        await db.commit()
        return "attached_existing"

    submitted = await _submit_video(entry.url)
    video_id = submitted.get("video_id")
    job_id = submitted.get("job_id")
    if not video_id:
        raise RuntimeError("submit response omitted video_id")
    video = await db.get(Video, uuid.UUID(str(video_id)))
    if video is None:
        raise RuntimeError(f"submitted video {video_id} was not found")
    if job_id:
        await _tag_job_as_auto_ingest(db, str(job_id))
    db.add(
        LaneVideoItem(
            lane_id=sub.lane_id,
            video_id=video.id,
            lane_subscription_id=sub.id,
            processing_job_id=uuid.UUID(str(job_id)) if job_id else None,
            source="lane_poll",
        )
    )
    await db.commit()
    return "submitted"


async def _process_one_lane_subscription(
    db,
    sub: LaneSubscription,
    *,
    submission_limit: int | None = None,
) -> dict[str, Any]:
    result = {
        "lane_id": str(sub.lane_id),
        "subscription_id": str(sub.id),
        "channel_name": None,
        "new_videos_found": 0,
        "submitted": 0,
        "attached_existing": 0,
        "already_attached": 0,
        "manual_review_blocked": 0,
        "skipped_reason": None,
    }
    channel = sub.channel or await db.get(Channel, sub.channel_id)
    result["channel_name"] = channel.name if channel else None
    if channel is None or not channel.youtube_channel_id:
        mark_poll_failure(sub, reason="channel missing youtube_channel_id")
        result["skipped_reason"] = "missing_youtube_channel_id"
        await db.commit()
        return result

    try:
        entries = await fetch_channel_feed(channel.youtube_channel_id)
    except SubscriptionError as exc:
        mark_poll_failure(sub, reason=str(exc))
        result["skipped_reason"] = f"rss_error: {exc}"
        await db.commit()
        return result

    new_entries = diff_new_videos(entries, list(sub.last_seen_video_ids or []))
    result["new_videos_found"] = len(new_entries)
    if not new_entries:
        mark_poll_success(sub, new_ids=[])
        await db.commit()
        return result

    reset_daily_counter_if_needed(sub)
    remaining_today = max(
        0,
        sub.max_videos_per_poll - (sub.videos_ingested_today or 0),
    )
    to_process = new_entries[:remaining_today]
    processed_ids: list[str] = []
    rejected_ids: list[str] = []
    deferred_count = 0

    for entry in to_process:
        if submission_limit is not None and result["submitted"] >= submission_limit:
            result["skipped_reason"] = "global_submission_cap_reached"
            break
        try:
            from app.services.video_classifier import classify_video_url

            classification = classify_video_url(entry.url)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "lane_ingest_classifier_error",
                lane_id=str(sub.lane_id),
                video_id=entry.video_id,
                error=str(exc),
            )
            from app.services.video_classifier import ClassificationResult

            classification = ClassificationResult(True, None)

        if not classification.is_regular:
            if classification.retry_later:
                deferred_count += 1
            else:
                rejected_ids.append(entry.video_id)
            continue

        try:
            disposition = await _attach_or_submit_lane_entry(db, sub, entry)
        except ManualReviewSubmissionBlocked as exc:
            processed_ids.append(entry.video_id)
            result["manual_review_blocked"] += 1
            logger.info(
                "lane_ingest_manual_review_preserved",
                lane_id=str(sub.lane_id),
                video_id=entry.video_id,
                status_code=exc.status_code,
                outcome="marked_seen_without_subscription_failure",
            )
            continue
        except Exception as exc:  # noqa: BLE001
            mark_poll_failure(
                sub,
                reason=f"lane attach/submit failed for {entry.video_id}: {exc}",
            )
            result["skipped_reason"] = f"submit_error: {exc}"
            await db.commit()
            return result
        result[disposition] += 1
        processed_ids.append(entry.video_id)
        sub.videos_ingested_today = (sub.videos_ingested_today or 0) + 1

    mark_poll_success(sub, new_ids=processed_ids + rejected_ids)
    result["deferred_for_retry"] = deferred_count
    await db.commit()
    return result


async def _run_poll() -> dict[str, Any]:
    circuit = get_download_circuit_state()
    if circuit.open:
        result = {
            "processed_subscriptions": 0,
            "total_ingested": 0,
            "soft_cap_crossed": False,
            "details": [],
            "processed_lane_subscriptions": 0,
            "lane_details": [],
            "download_circuit": circuit_state_payload(circuit),
            "skipped_reason": "download_circuit_open",
        }
        logger.warning("poll_subscriptions_deferred", **result["download_circuit"])
        return result

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    total_ingested = 0
    stats: list[dict[str, Any]] = []
    lane_stats: list[dict[str, Any]] = []
    soft_cap_crossed = False  # notify once per run when auto-ingest spend
                              # crosses the soft cap. Polling continues.
    remaining_submission_slots = max(0, settings.auto_ingest_max_submissions_per_run)

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
                circuit = get_download_circuit_state()
                if circuit.open or remaining_submission_slots <= 0:
                    break

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
                s = await _process_one_subscription(
                    db,
                    sub,
                    budget_remaining=1e9,
                    submission_limit=remaining_submission_slots,
                )
                stats.append(s)
                total_ingested += int(s.get("ingested") or 0)
                remaining_submission_slots -= int(s.get("ingested") or 0)

            lane_subscriptions = (
                await db.execute(
                    select(LaneSubscription).order_by(
                        LaneSubscription.last_polled_at.asc().nullsfirst()
                    )
                )
            ).scalars().all()
            for lane_subscription in lane_subscriptions:
                if not is_due_for_poll(lane_subscription):
                    continue
                circuit = get_download_circuit_state()
                if circuit.open or remaining_submission_slots <= 0:
                    break
                lane_result = await _process_one_lane_subscription(
                    db,
                    lane_subscription,
                    submission_limit=remaining_submission_slots,
                )
                lane_stats.append(lane_result)
                remaining_submission_slots -= int(lane_result.get("submitted") or 0)
    finally:
        await engine.dispose()

    result = {
        "processed_subscriptions": len(stats),
        "total_ingested": total_ingested,
        "soft_cap_crossed": soft_cap_crossed,
        "details": stats,
        "processed_lane_subscriptions": len(lane_stats),
        "lane_details": lane_stats,
        "download_circuit": circuit_state_payload(get_download_circuit_state()),
        "submission_cap": settings.auto_ingest_max_submissions_per_run,
        "submission_slots_remaining": remaining_submission_slots,
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
