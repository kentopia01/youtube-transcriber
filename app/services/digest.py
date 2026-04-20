"""Morning digest — synthesizes the last 24h of library activity into a
Chief-of-staff style executive brief, delivered via Telegram.

Design:
- Cheap input gathering (single pass of SQL) over a configurable window.
- One Sonnet call with a sharp, objective CoS system prompt.
- Output is Markdown, rendered through the existing telegram_markdown →
  HTML path so chips and bold render properly in the chat.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import anthropic
import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.channel import Channel
from app.models.job import Job
from app.models.llm_usage import LlmUsage
from app.models.persona import Persona
from app.models.summary import Summary
from app.models.video import Video

logger = structlog.get_logger()


CHIEF_OF_STAFF_SYSTEM_PROMPT = """You are a Chief of Staff reporting to an \
executive. Your job is to turn overnight activity in their YouTube \
research library into a crisp morning brief.

Voice and tone:
- Objective, sharp, executive-ready. Never breezy. Never hype.
- Headline first. Support second. Don't bury the lede.
- Concrete numbers before qualitative claims.
- No emoji except where specified below.
- Do not invent facts. If data is thin, say so and stop.

Format:

**Opener** — one sentence on the shape of the night. Examples:
"Quiet night. Three videos processed." · "Heavy AI news: four ingests, one \
cross-cutting theme." · "Nothing new overnight."

**Worth your time today** — the single video most worth watching, with 2-3 \
sentences on WHY. Name it precisely. If multiple tie, pick one.

**Also ingested** — one-line summaries of the rest (1-4 lines). Name each \
piece precisely. Skip entirely if nothing else.

**Needs attention** — any pipeline failures or persona issues. "None." if \
clean.

**Ledger** — one line with auto-ingest LLM spend, persona refreshes, and \
subscriptions touched.

End with a single follow-up prompt starting with "Next question:" that the \
executive might ask a researcher — short, specific, useful.

Use `**bold**` for section headings. No bullet lists. No markdown other \
than bold and plain Markdown links `[text](url)` if you reference a \
source video.

If the inputs show zero activity across the board, produce only the \
Opener and a single "Ledger" line. Keep it under 50 words."""


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

    def to_prompt_block(self) -> str:
        """Render the inputs as a human-readable input block for the LLM."""
        lines = [
            f"Window: {self.window_start:%Y-%m-%d %H:%M UTC} to {self.window_end:%Y-%m-%d %H:%M UTC}",
            "",
        ]
        if self.videos_completed:
            lines.append(f"Videos completed ({len(self.videos_completed)}):")
            for v in self.videos_completed:
                dur = _fmt_duration(v.get("duration_seconds"))
                summary = (v.get("summary_excerpt") or "").strip().replace("\n", " ")[:400]
                lines.append(
                    f"  - channel={v['channel_name']} title={v['title']!r} duration={dur}"
                    + (f"\n    summary: {summary}" if summary else "")
                )
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
            f"Active subscriptions: {len(self.subscription_names)} "
            f"({', '.join(self.subscription_names[:5])}"
            + (f", +{len(self.subscription_names) - 5} more" if len(self.subscription_names) > 5 else "")
            + ")"
        )
        return "\n".join(lines)


def _fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return "—"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, _ = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def gather_digest_inputs(db: Session, window_hours: int = 24) -> DigestInput:
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=window_hours)

    # Completed videos with summary excerpt
    completed_rows = db.execute(
        select(Video, Channel, Summary)
        .outerjoin(Channel, Channel.id == Video.channel_id)
        .outerjoin(Summary, Summary.video_id == Video.id)
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
        }
        for (v, c, s) in completed_rows
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
    )


def render_digest_via_llm(
    inputs: DigestInput,
    *,
    model: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Call Sonnet to produce the digest. Returns the full result dict."""
    model = model or settings.anthropic_summary_model
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
