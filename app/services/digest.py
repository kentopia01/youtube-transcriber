"""Morning digest — synthesizes the last 24h of library activity into a
Chief-of-staff style executive brief, delivered via Telegram.

Design:
- Cheap input gathering (single pass of SQL) over a configurable window.
- One Sonnet call with a sharp, objective CoS system prompt.
- Output is Markdown, rendered through the existing telegram_markdown →
  HTML path so chips and bold render properly in the chat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import anthropic
import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.channel import Channel
from app.models.job import Job, PIPELINE_ACTIVE_STATUSES
from app.models.llm_usage import LlmUsage
from app.models.persona import Persona
from app.models.summary import Summary
from app.models.video import Video
from app.models.video_report import VideoReport

logger = structlog.get_logger()


CHIEF_OF_STAFF_SYSTEM_PROMPT = """You are a Chief of Staff reporting to an \
executive. Your job is to turn overnight activity in their YouTube \
research library into a crisp morning operations and intelligence brief.

Voice and tone:
- Objective, sharp, executive-ready. Never breezy. Never hype.
- Headline first. Support second. Don't bury the lede.
- Concrete numbers before qualitative claims.
- No emoji except where specified below.
- Do not invent facts. If data is thin, say so and stop.
- Do not nudge the user to chat with a video or open a channel.

Format:

**Opener** — one sentence on the shape of the night. Examples:
"Quiet night. Three videos processed." · "Heavy AI news: four ingests, one \
cross-cutting theme." · "Nothing new overnight; pipeline clean."

**Worth your time today** — the single completed video/report most worth \
reading, with 2-3 sentences on WHY. Name it precisely. If multiple tie, pick one.
Skip if nothing completed.

**Also processed** — one-line summaries of the rest (1-4 lines). Name each \
piece precisely. Skip entirely if nothing else.

**Pipeline status** — summarize queued/pending/running/retrying work, including \
manual-review items and retry context. If clean, say "No pending retries or \
manual-review items."

**Needs attention** — failed videos, manual-review items, delivery failures, or \
persona issues. "None." if clean.

**Ledger** — one line with report delivery counts, auto-ingest LLM spend, manual \
LLM spend, active subscriptions, and a short health summary.

Use `**bold**` for section headings. Keep it compact. No markdown other than \
bold and plain Markdown links `[text](url)` if you reference a source video.

If the inputs show zero activity and zero pending/retry/failure state, produce \
only the Opener, Pipeline status, and Ledger. Keep it under 80 words."""


@dataclass
class DigestInput:
    window_start: datetime
    window_end: datetime
    videos_completed: list[dict[str, Any]]
    videos_failed: list[dict[str, Any]]
    personas_touched: list[dict[str, Any]]
    cost_auto_ingest_usd: float
    cost_manual_usd: float
    subscription_names: list[str]
    pipeline_status_counts: dict[str, int] = field(default_factory=dict)
    pending_jobs: list[dict[str, Any]] = field(default_factory=list)
    retrying_jobs: list[dict[str, Any]] = field(default_factory=list)
    manual_review_jobs: list[dict[str, Any]] = field(default_factory=list)
    report_delivery_counts: dict[str, int] = field(default_factory=dict)
    health_summary: dict[str, Any] = field(default_factory=dict)

    def to_prompt_block(self) -> str:
        """Render the inputs as a human-readable input block for the LLM."""
        lines = [
            f"Window: {self.window_start:%Y-%m-%d %H:%M UTC} to {self.window_end:%Y-%m-%d %H:%M UTC}",
            "",
            "Activity totals:",
            f"  - completed_videos={len(self.videos_completed)} failed_videos={len(self.videos_failed)} personas_updated={len(self.personas_touched)}",
            f"  - active_pipeline_jobs={sum(self.pipeline_status_counts.values())} "
            f"status_counts={_fmt_counts(self.pipeline_status_counts)}",
            f"  - report_delivery_counts={_fmt_counts(self.report_delivery_counts)}",
            "",
        ]
        if self.videos_completed:
            lines.append(f"Videos completed ({len(self.videos_completed)}):")
            for v in self.videos_completed:
                dur = _fmt_duration(v.get("duration_seconds"))
                summary = (v.get("summary_excerpt") or "").strip().replace("\n", " ")[:400]
                report_status = v.get("report_delivery_status") or "unknown"
                lines.append(
                    f"  - channel={v['channel_name']} title={v['title']!r} duration={dur} report_delivery={report_status}"
                    + (f"\n    summary: {summary}" if summary else "")
                )
            lines.append("")
        if self.pending_jobs:
            lines.append(f"Queued/pending/running pipeline jobs ({len(self.pending_jobs)}):")
            for job in self.pending_jobs:
                lines.append(_fmt_job_line(job))
            lines.append("")
        if self.retrying_jobs:
            lines.append(f"Retrying pipeline jobs ({len(self.retrying_jobs)}):")
            for job in self.retrying_jobs:
                lines.append(_fmt_job_line(job, include_retry=True))
            lines.append("")
        if self.manual_review_jobs:
            lines.append(f"Manual-review items ({len(self.manual_review_jobs)}):")
            for job in self.manual_review_jobs:
                lines.append(_fmt_job_line(job, include_retry=True, include_error=True))
            lines.append("")
        if self.videos_failed:
            lines.append(f"Pipeline failures ({len(self.videos_failed)}):")
            for f in self.videos_failed:
                lines.append(
                    f"  - channel={f['channel_name']} title={f['title']!r} "
                    f"reason={(f.get('error_message') or '')[:200]}"
                )
            lines.append("")
        if self.personas_touched:
            lines.append(f"Persona updates ({len(self.personas_touched)}):")
            for p in self.personas_touched:
                lines.append(
                    f"  - {p['display_name']} (channel) generated_at={p['generated_at']:%Y-%m-%d %H:%M}"
                )
            lines.append("")
        lines.append(
            f"LLM spend this window: auto-ingest=${self.cost_auto_ingest_usd:.2f}, "
            f"manual=${self.cost_manual_usd:.2f}"
        )
        lines.append(
            f"Health: {_fmt_health(self.health_summary)}"
        )
        lines.append(
            f"Active subscriptions: {len(self.subscription_names)} "
            f"({', '.join(self.subscription_names[:5])}"
            + (f", +{len(self.subscription_names) - 5} more" if len(self.subscription_names) > 5 else "")
            + ")"
        )
        return "\n".join(lines)


def _fmt_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))


def _fmt_job_line(job: dict[str, Any], *, include_retry: bool = False, include_error: bool = False) -> str:
    parts = [
        f"channel={job.get('channel_name') or '(no channel)'}",
        f"title={job.get('title')!r}",
        f"status={job.get('status') or 'unknown'}",
    ]
    if job.get("current_stage"):
        parts.append(f"stage={job['current_stage']}")
    if job.get("progress_pct") is not None:
        parts.append(f"progress={job['progress_pct']:.0f}%")
    if include_retry:
        parts.append(f"attempt={job.get('attempt_number') or 1}")
        if job.get("attempt_creation_reason"):
            parts.append(f"retry_reason={job['attempt_creation_reason']}")
        if job.get("failure_signature_count"):
            parts.append(f"failure_signature_count={job['failure_signature_count']}")
    if include_error and job.get("error_message"):
        parts.append(f"error={(job['error_message'] or '')[:180]}")
    return "  - " + " ".join(parts)


def _fmt_health(health: dict[str, Any]) -> str:
    if not health:
        return "not captured"
    active = health.get("active_jobs", 0)
    workers = health.get("active_workers", 0)
    manual = health.get("manual_review", 0)
    failed = health.get("failed_undismissed", 0)
    last_activity = health.get("last_activity_at") or "none"
    return (
        f"active_jobs={active}, active_workers={workers}, "
        f"manual_review={manual}, failed_undismissed={failed}, last_activity={last_activity}"
    )


def _fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return "—"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, _ = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def _job_digest_dict(job: Job, video: Video | None, channel: Channel | None) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "video_id": str(job.video_id) if job.video_id else None,
        "title": video.title if video and video.title else job.display_name,
        "channel_name": channel.name if channel else "(no channel)",
        "status": job.status,
        "current_stage": job.current_stage,
        "progress_pct": job.progress_pct,
        "attempt_number": job.attempt_number,
        "attempt_creation_reason": job.attempt_creation_reason,
        "failure_signature": job.failure_signature,
        "failure_signature_count": job.failure_signature_count,
        "recovery_status": job.recovery_status,
        "error_message": job.error_message,
        "worker_hostname": job.worker_hostname,
        "stage_updated_at": job.stage_updated_at,
        "last_activity_at": job.last_activity_at,
    }


def gather_digest_inputs(db: Session, window_hours: int = 24) -> DigestInput:
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=window_hours)

    # Completed videos with summary excerpt
    completed_rows = db.execute(
        select(Video, Channel, Summary, VideoReport)
        .outerjoin(Channel, Channel.id == Video.channel_id)
        .outerjoin(Summary, Summary.video_id == Video.id)
        .outerjoin(VideoReport, VideoReport.video_id == Video.id)
        .where(Video.status == "completed", Video.updated_at >= start)
        .order_by(Video.updated_at.desc())
        .limit(30)
    ).all()
    videos_completed = [
        {
            "id": str(v.id),
            "title": v.title,
            "duration_seconds": v.duration_seconds,
            "channel_name": c.name if c else "(no channel)",
            "summary_excerpt": (s.content if s and s.content else "")[:600],
            "report_delivery_status": r.delivery_status if r else None,
        }
        for (v, c, s, r) in completed_rows
    ]

    # Failures not dismissed
    failed_rows = db.execute(
        select(Video, Channel)
        .outerjoin(Channel, Channel.id == Video.channel_id)
        .where(
            Video.status == "failed",
            Video.updated_at >= start,
            Video.dismissed_at.is_(None),
        )
        .order_by(Video.updated_at.desc())
        .limit(10)
    ).all()
    videos_failed = [
        {
            "title": v.title,
            "channel_name": c.name if c else "(no channel)",
            "error_message": v.error_message,
        }
        for (v, c) in failed_rows
    ]

    # Active/retrying/manual-review pipeline state
    pipeline_count_rows = db.execute(
        select(Job.status, func.count())
        .where(
            Job.job_type == "pipeline",
            Job.status.in_(PIPELINE_ACTIVE_STATUSES),
            Job.hidden_from_queue.is_(False),
        )
        .group_by(Job.status)
    ).all()
    pipeline_status_counts = {status: int(count) for status, count in pipeline_count_rows}

    active_rows = db.execute(
        select(Job, Video, Channel)
        .outerjoin(Video, Video.id == Job.video_id)
        .outerjoin(Channel, Channel.id == func.coalesce(Job.channel_id, Video.channel_id))
        .where(
            Job.job_type == "pipeline",
            Job.status.in_(PIPELINE_ACTIVE_STATUSES),
            Job.hidden_from_queue.is_(False),
        )
        .order_by(Job.created_at.asc())
        .limit(20)
    ).all()
    active_jobs = [_job_digest_dict(j, v, c) for (j, v, c) in active_rows]
    retrying_jobs = [
        j
        for j in active_jobs
        if (j.get("attempt_number") or 1) > 1 or j.get("attempt_creation_reason")
    ]
    pending_jobs = [j for j in active_jobs if j not in retrying_jobs][:10]

    manual_review_rows = db.execute(
        select(Job, Video, Channel)
        .outerjoin(Video, Video.id == Job.video_id)
        .outerjoin(Channel, Channel.id == func.coalesce(Job.channel_id, Video.channel_id))
        .where(
            Job.job_type == "pipeline",
            Job.recovery_status == "manual_review",
            Job.hidden_from_queue.is_(False),
        )
        .order_by(Job.created_at.desc())
        .limit(10)
    ).all()
    manual_review_jobs = [_job_digest_dict(j, v, c) for (j, v, c) in manual_review_rows]

    report_delivery_rows = db.execute(
        select(VideoReport.delivery_status, func.count())
        .where(VideoReport.updated_at >= start)
        .group_by(VideoReport.delivery_status)
    ).all()
    report_delivery_counts = {status: int(count) for status, count in report_delivery_rows}

    failed_undismissed_count = int(
        db.execute(
            select(func.count()).where(
                Video.status == "failed",
                Video.dismissed_at.is_(None),
            )
        ).scalar()
        or 0
    )
    active_workers = {
        job.get("worker_hostname")
        for job in active_jobs
        if job.get("worker_hostname")
    }
    last_activity_candidates = [
        job.get("last_activity_at") or job.get("stage_updated_at")
        for job in active_jobs
        if job.get("last_activity_at") or job.get("stage_updated_at")
    ]
    health_summary = {
        "active_jobs": sum(pipeline_status_counts.values()),
        "active_workers": len(active_workers),
        "manual_review": len(manual_review_jobs),
        "failed_undismissed": failed_undismissed_count,
        "last_activity_at": max(last_activity_candidates).isoformat() if last_activity_candidates else None,
    }

    # Personas generated/refreshed in window
    persona_rows = db.execute(
        select(Persona)
        .where(Persona.generated_at >= start)
        .order_by(Persona.generated_at.desc())
    ).scalars().all()
    personas_touched = [
        {
            "display_name": p.display_name,
            "generated_at": p.generated_at,
        }
        for p in persona_rows
    ]

    # Cost split
    auto_cost = float(
        db.execute(
            select(func.coalesce(func.sum(LlmUsage.estimated_cost_usd), 0.0)).where(
                LlmUsage.created_at >= start,
                LlmUsage.source == "auto_ingest",
            )
        ).scalar()
        or 0.0
    )
    manual_cost = float(
        db.execute(
            select(func.coalesce(func.sum(LlmUsage.estimated_cost_usd), 0.0)).where(
                LlmUsage.created_at >= start,
                LlmUsage.source.is_(None),
            )
        ).scalar()
        or 0.0
    )

    # Active subscriptions
    from app.models.channel_subscription import ChannelSubscription

    sub_rows = db.execute(
        select(Channel.name)
        .join(ChannelSubscription, ChannelSubscription.channel_id == Channel.id)
        .where(ChannelSubscription.enabled.is_(True))
        .order_by(Channel.name)
    ).all()
    subscription_names = [r[0] for r in sub_rows if r[0]]

    return DigestInput(
        window_start=start,
        window_end=now,
        videos_completed=videos_completed,
        videos_failed=videos_failed,
        personas_touched=personas_touched,
        cost_auto_ingest_usd=auto_cost,
        cost_manual_usd=manual_cost,
        subscription_names=subscription_names,
        pipeline_status_counts=pipeline_status_counts,
        pending_jobs=pending_jobs,
        retrying_jobs=retrying_jobs,
        manual_review_jobs=manual_review_jobs,
        report_delivery_counts=report_delivery_counts,
        health_summary=health_summary,
    )


def render_digest_via_llm(
    inputs: DigestInput,
    *,
    model: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Call Sonnet to produce the digest. Returns the full result dict."""
    model = model or settings.digest_model
    api_key = api_key or settings.anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")

    from app.services.cost_tracker import check_budget, record_usage

    check_budget()
    client = anthropic.Anthropic(api_key=api_key)
    user_message = inputs.to_prompt_block()

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=CHIEF_OF_STAFF_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    record_usage(model, response.usage.input_tokens, response.usage.output_tokens)
    text = response.content[0].text

    return {
        "text": text,
        "model": response.model,
        "prompt_tokens": response.usage.input_tokens,
        "completion_tokens": response.usage.output_tokens,
        "window_start": inputs.window_start.isoformat(),
        "window_end": inputs.window_end.isoformat(),
    }


__all__ = [
    "CHIEF_OF_STAFF_SYSTEM_PROMPT",
    "DigestInput",
    "gather_digest_inputs",
    "render_digest_via_llm",
]
