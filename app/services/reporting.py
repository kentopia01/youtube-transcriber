"""Styled per-video report generation.

This module intentionally renders deterministic HTML from already-persisted
transcript and summary data. The report is a delivery artifact, not a new
pipeline truth source; failures here should never make a completed transcript
look failed.

Report persistence is intentionally one current summary report per video.
Regeneration updates that row; ``report_type`` is a canonical label, not a
variant dimension.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from app.config import settings
from app.models.channel import Channel
from app.models.summary import Summary
from app.models.transcription import Transcription
from app.models.video import Video
from app.models.video_report import SUMMARY_REPORT_TYPE, VideoReport
from app.services.summary_markdown import (
    bullet_points_from_markdown,
    extract_heading_sections,
    extract_markdown_section,
    first_content_block,
)
from app.services.summary_quality import validate_report_depth

logger = structlog.get_logger()


@dataclass
class ReportSection:
    title: str
    html: str


@dataclass
class ReportRenderData:
    title: str
    published_date: str | None
    channel_name: str | None
    video_url: str | None
    duration: str | None
    at_a_glance_html: str
    executive_summary_html: str
    scan_html: str
    key_points: list[str]
    key_points_html: list[str]
    watch_verdict_html: str | None
    ken_relevance_html: str | None
    action_items_html: str | None
    detailed_brief_html: str | None
    concepts_html: str | None
    operator_notes_html: str | None
    source_metadata_html: str | None
    brief_sections: list[ReportSection]
    generated_at: str
    word_count: int | None = None
    model: str | None = None


class ReportQualityError(ValueError):
    """Raised when an existing summary is too thin to ship as a report."""


def _template_env() -> Environment:
    template_dir = Path(__file__).resolve().parents[1] / "report_templates"
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(("html", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _fmt_duration(seconds: float | None) -> str | None:
    if not seconds:
        return None
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value[:80] or "video-report"


def _artifact_root() -> Path:
    root = Path(settings.report_artifact_dir).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    return root


def _markdownish_to_html(text: str | None) -> str:
    """Small safe markdown-ish renderer for existing summaries.

    Supports headings and bullet lists well enough for report delivery without
    adding another dependency or trusting model-emitted HTML.
    """
    if not text:
        return "<p>No summary was generated for this video.</p>"

    lines = text.strip().splitlines()
    parts: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            parts.append("</ul>")
            in_list = False

    for raw in lines:
        line = raw.strip()
        if not line:
            close_list()
            continue
        if line in {"---", "***"}:
            close_list()
            continue
        if line.startswith("### "):
            close_list()
            parts.append(f"<h3>{_inline_markdown(line[4:])}</h3>")
        elif line.startswith("## "):
            close_list()
            parts.append(f"<h3>{_inline_markdown(line[3:])}</h3>")
        elif line.startswith("# "):
            close_list()
            parts.append(f"<h3>{_inline_markdown(line[2:])}</h3>")
        elif line.startswith(("- ", "* ")):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{_inline_markdown(line[2:])}</li>")
        elif re.match(r"^\d+\.\s+", line):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            item_text = re.sub(r"^\d+\.\s+", "", line)
            parts.append(f"<li>{_inline_markdown(item_text)}</li>")
        else:
            close_list()
            parts.append(f"<p>{_inline_markdown(line)}</p>")
    close_list()
    return "\n".join(parts)


def markdownish_to_safe_html(text: str | None) -> str:
    """Public escaping-first renderer for persisted/model-authored Markdown."""
    return _markdownish_to_html(text)


def _inline_markdown(text: str) -> str:
    escaped = escape(text, quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
    return escaped


def _inline_markdown_list(items: list[str]) -> list[str]:
    return [_inline_markdown(item) for item in items]


def _scan_from_summary(summary: str | None) -> str | None:
    return (
        extract_markdown_section(
            summary,
            [
                "30-second take",
                "30 second take",
                "30-second scan",
                "At-a-Glance",
                "At a Glance",
                "executive summary",
                "bottom line",
                "summary",
            ],
        )
        or first_content_block(summary)
    )


def _key_points_from_summary(summary: str | None, *, limit: int = 6) -> list[str]:
    if not summary:
        return []

    for section_names in (
        ["Key Takeaways", "Key takes", "Key takeaways"],
        ["Takeaways", "Action items"],
        ["Key points", "Useful details"],
    ):
        points = bullet_points_from_markdown(
            extract_markdown_section(summary, section_names),
            limit=limit,
        )
        if points:
            return points

    points = bullet_points_from_markdown(summary, limit=limit)
    if points:
        return points

    sentences = re.split(r"(?<=[.!?])\s+", summary.strip())
    return [s for s in sentences if s][:limit]


def _section_html(summary: str | None, headings: list[str]) -> str | None:
    content = extract_markdown_section(summary, headings)
    if not content:
        return None
    return _markdownish_to_html(content)


def _section_content(summary: str | None, headings: list[str]) -> str | None:
    return extract_markdown_section(summary, headings)


def _combined_section_html(summary: str | None, section_specs: list[tuple[str, list[str]]]) -> str | None:
    parts: list[str] = []
    for title, headings in section_specs:
        content = _section_content(summary, headings)
        if content:
            parts.append(f"### {title}\n{content}")
    if not parts:
        return None
    return _markdownish_to_html("\n\n".join(parts))


def _at_a_glance_html(summary: str | None) -> str:
    return (
        _section_html(summary, ["At-a-Glance", "At a Glance"])
        or _combined_section_html(
            summary,
            [
                ("Scan", ["30-second take", "30 second take", "30-second scan"]),
                ("Verdict", ["Watch verdict", "Verdict"]),
            ],
        )
        or _markdownish_to_html(_scan_from_summary(summary))
    )


def _executive_summary_html(summary: str | None) -> str:
    return (
        _section_html(summary, ["Executive Summary", "Overall Summary"])
        or _markdownish_to_html(_scan_from_summary(summary))
    )


def _detailed_brief_html(summary: str | None) -> str | None:
    return _section_html(summary, ["Detailed Brief"]) or _combined_section_html(
        summary,
        [
            ("Useful Details", ["Useful details", "Details", "Numbers and named references"]),
            ("Caveats / Counterpoints", ["Caveats / counterpoints", "Caveats", "Counterpoints"]),
            ("Additional Context", ["Additional Context"]),
        ],
    )


def _concepts_html(summary: str | None) -> str | None:
    explicit = _section_html(
        summary,
        ["Notable Concepts & Terms", "Notable Concepts and Terms", "Concepts", "Terms"],
    )
    if explicit:
        return explicit

    fallback_source = _section_content(summary, ["Useful details", "Details", "Key Takeaways", "Key takes"])
    concepts: list[str] = []
    for point in bullet_points_from_markdown(fallback_source, limit=8):
        match = re.match(r"(?:\*\*)?([^:*]{2,60})(?:\*\*)?\s*:\s+(.+)", point)
        if not match:
            continue
        term = match.group(1).strip()
        meaning = match.group(2).strip()
        if term and meaning:
            concepts.append(f"- {term}: {meaning}")
        if len(concepts) >= 5:
            break
    if concepts:
        return _markdownish_to_html("\n".join(concepts))
    return None


def _operator_notes_html(summary: str | None) -> str | None:
    return _section_html(
        summary,
        [
            "Operator Notes / Why Ken Should Care",
            "Operator Notes",
            "Why Ken Should Care",
            "Ken relevance",
            "Why it matters to Ken",
        ],
    )


def _source_metadata_html(summary: str | None) -> str | None:
    return _section_html(summary, ["Source/Metadata", "Source Metadata", "Metadata"])


def _section_preview_html(
    summary: str | None,
    headings: list[str],
    *,
    max_bullets: int = 2,
    max_chars: int | None = None,
) -> str | None:
    content = extract_markdown_section(summary, headings)
    if not content:
        return None

    first_block = first_content_block(content, max_lines=2)
    bullets = bullet_points_from_markdown(content, limit=max_bullets)
    parts: list[str] = []
    if first_block:
        if max_chars and len(first_block) > max_chars:
            cutoff = first_block.rfind(".", 0, max_chars)
            if cutoff < max_chars // 2:
                cutoff = max_chars
            first_block = first_block[: cutoff + 1].rstrip()
        parts.append(_markdownish_to_html(first_block))
    if bullets:
        parts.append(
            "<ul>"
            + "".join(f"<li>{_inline_markdown(point)}</li>" for point in bullets)
            + "</ul>"
        )
    return "\n".join(parts) if parts else _markdownish_to_html(content)


def _brief_sections_from_summary(summary: str | None) -> list[ReportSection]:
    """Build the body sections after the decision-first top of the report."""
    if not summary:
        return []

    sections: list[ReportSection] = []
    section_specs = [
        ("Ken Relevance", ["Ken relevance", "Why it matters to Ken"]),
        ("Useful Details", ["Useful details", "Details", "Numbers and named references"]),
        ("Caveats / Counterpoints", ["Caveats / counterpoints", "Caveats", "Counterpoints"]),
    ]
    used_headings = {
        "30 second take",
        "30 second scan",
        "executive summary",
        "bottom line",
        "summary",
        "key takes",
        "key takeaways",
        "takeaways",
        "key points",
        "action items",
        "actions",
        "next steps",
        "actionable ideas",
        "ken relevance",
        "why it matters to ken",
        "at a glance",
        "watch verdict",
        "verdict",
        "useful details",
        "details",
        "numbers and named references",
        "caveats counterpoints",
        "caveats",
        "counterpoints",
    }

    for title, headings in section_specs:
        html = _section_html(summary, headings)
        if html:
            sections.append(ReportSection(title=title, html=html))

    leftovers: list[str] = []
    for heading, content in extract_heading_sections(summary).items():
        if heading not in used_headings and content:
            leftovers.append(f"## {heading.title()}\n{content}")
    if leftovers:
        sections.append(
            ReportSection(
                title="Additional Context",
                html=_markdownish_to_html("\n\n".join(leftovers)),
            )
        )

    return sections


def _clean_caption_text(value: str | None) -> str:
    text = re.sub(r"[#>*_`]", "", value or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    cutoff = value.rfind(".", 0, limit)
    if cutoff < limit // 2:
        cutoff = value.rfind(" ", 0, limit)
    if cutoff < limit // 2:
        cutoff = limit
    return value[:cutoff].rstrip(" .") + "..."


def _labeled_lines(section: str | None) -> dict[str, str]:
    labels: dict[str, str] = {}
    for raw in (section or "").splitlines():
        line = raw.strip()
        if line.startswith(("- ", "* ")):
            line = line[2:].strip()
        match = re.match(r"([^:]{2,50}):\s+(.+)", line)
        if match:
            labels[match.group(1).strip().lower()] = _clean_caption_text(match.group(2))
    return labels


def _operator_action_points(summary: str | None, *, limit: int = 3) -> list[str]:
    points = bullet_points_from_markdown(
        _section_content(
            summary,
            [
                "Operator Notes / Why Ken Should Care",
                "Operator Notes",
                "Why Ken Should Care",
                "Ken relevance",
                "Why it matters to Ken",
            ],
        ),
        limit=limit,
    )
    cleaned = [_clean_caption_text(point) for point in points]
    cleaned = [point for point in cleaned if point]
    if cleaned:
        return cleaned[:limit]

    implications: list[str] = []
    for point in _key_points_from_summary(summary, limit=limit):
        match = re.search(r"\bImplication:\s*(.+?)(?:\s+\|\s+\w+:|$)", point)
        text = _clean_caption_text(match.group(1) if match else point)
        if text:
            implications.append(text)
    return implications[:limit]


def build_report_caption(summary: str | None, *, max_chars: int = 650) -> str | None:
    """Build a Telegram-first decision brief from a summary/report markdown."""
    at_a_glance = _labeled_lines(extract_markdown_section(summary, ["At-a-Glance", "At a Glance"]))
    verdict = at_a_glance.get("verdict")
    thesis = at_a_glance.get("core thesis") or _clean_caption_text(first_content_block(summary, max_lines=1))
    why = at_a_glance.get("why it matters")
    best_use = at_a_glance.get("best use")
    actions = _operator_action_points(summary, limit=3)

    parts: list[str] = []
    if verdict:
        parts.append(f"Verdict: {verdict}")
    if thesis:
        parts.append("Thesis: " + _truncate_text(thesis, 220))
    if why:
        parts.append("Why it matters: " + _truncate_text(why, 220))
    if actions:
        parts.append("Do next:")
        parts.extend("• " + _truncate_text(point, 150) for point in actions)
    elif best_use:
        parts.append("Best use: " + _truncate_text(best_use, 180))

    text = "\n".join(parts).strip()
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def build_report_render_data(
    *,
    video: Video,
    channel: Channel | None,
    summary: Summary | None,
    transcription: Transcription | None = None,
) -> ReportRenderData:
    summary_text = summary.content if summary else None
    published = None
    if video.published_at:
        published = video.published_at.astimezone(UTC).strftime("%Y-%m-%d")

    return ReportRenderData(
        title=video.title,
        published_date=published,
        channel_name=channel.name if channel else None,
        video_url=video.url,
        duration=_fmt_duration(video.duration_seconds),
        at_a_glance_html=_at_a_glance_html(summary_text),
        executive_summary_html=_executive_summary_html(summary_text),
        scan_html=_markdownish_to_html(_scan_from_summary(summary_text)),
        key_points=_key_points_from_summary(summary_text),
        key_points_html=_inline_markdown_list(_key_points_from_summary(summary_text)),
        watch_verdict_html=_section_preview_html(
            summary_text,
            ["Watch verdict", "Verdict", "At-a-Glance", "At a Glance"],
            max_bullets=0,
            max_chars=420,
        ),
        ken_relevance_html=_section_preview_html(
            summary_text,
            [
                "Operator Notes / Why Ken Should Care",
                "Operator Notes",
                "Why Ken Should Care",
                "Ken relevance",
                "Why it matters to Ken",
            ],
        ),
        action_items_html=_section_html(
            summary_text,
            ["Action items", "Actions", "Next steps", "Actionable ideas"],
        ),
        detailed_brief_html=_detailed_brief_html(summary_text),
        concepts_html=_concepts_html(summary_text),
        operator_notes_html=_operator_notes_html(summary_text),
        source_metadata_html=_source_metadata_html(summary_text),
        brief_sections=_brief_sections_from_summary(summary_text),
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        word_count=transcription.word_count if transcription else None,
        model=summary.model if summary else None,
    )


def render_video_report_html(data: ReportRenderData) -> str:
    template = _template_env().get_template("report_video.html")
    return template.render(report=data)


def render_video_report_markdown(data: ReportRenderData) -> str:
    lines = [f"# {data.title}", ""]
    if data.channel_name or data.duration:
        lines.append(" · ".join(p for p in [data.channel_name, data.duration] if p))
        lines.append("")
    lines.append("## At-a-Glance")
    lines.append(re.sub(r"<[^>]+>", "", data.at_a_glance_html))
    lines.extend(["", "## Executive Summary"])
    lines.append(re.sub(r"<[^>]+>", "", data.executive_summary_html))
    if data.key_points:
        lines.extend(["", "## Key Takeaways"])
        lines.extend(f"- {p}" for p in data.key_points)
    if data.detailed_brief_html:
        lines.extend(["", "## Detailed Brief"])
        lines.append(re.sub(r"<[^>]+>", "", data.detailed_brief_html))
    if data.concepts_html:
        lines.extend(["", "## Notable Concepts & Terms"])
        lines.append(re.sub(r"<[^>]+>", "", data.concepts_html))
    if data.operator_notes_html:
        lines.extend(["", "## Operator Notes / Why Ken Should Care"])
        lines.append(re.sub(r"<[^>]+>", "", data.operator_notes_html))
    if data.source_metadata_html:
        lines.extend(["", "## Source/Metadata"])
        lines.append(re.sub(r"<[^>]+>", "", data.source_metadata_html))
    return "\n".join(lines).strip() + "\n"


def generate_video_report(
    db: Session,
    video_id: uuid.UUID | str,
    *,
    commit: bool = True,
) -> VideoReport:
    video_uuid = uuid.UUID(str(video_id))
    video = db.get(Video, video_uuid)
    if not video:
        raise ValueError(f"Video not found: {video_id}")

    transcription = db.query(Transcription).filter(Transcription.video_id == video_uuid).first()
    summary = db.query(Summary).filter(Summary.video_id == video_uuid).first()
    channel = db.get(Channel, video.channel_id) if video.channel_id else None
    report_depth = validate_report_depth(
        summary.content if summary else None,
        word_count=transcription.word_count if transcription else None,
        duration_seconds=video.duration_seconds,
    )
    if report_depth.is_too_thin:
        logger.warning(
            "video_report_quality_gate_failed",
            video_id=str(video_uuid),
            title=video.title,
            word_count=transcription.word_count if transcription else None,
            duration_seconds=video.duration_seconds,
            errors=report_depth.errors,
        )
        raise ReportQualityError(
            "Summary is too thin to render as a report for a long/substantive video: "
            + "; ".join(report_depth.errors)
        )

    data = build_report_render_data(
        video=video,
        channel=channel,
        summary=summary,
        transcription=transcription,
    )
    html = render_video_report_html(data)
    markdown = render_video_report_markdown(data)

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    safe_name = _slugify(video.title)
    artifact_dir = _artifact_root() / today / str(video.id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{safe_name}_report.html"
    artifact_path.write_text(html, encoding="utf-8")

    # Intentionally upsert by video_id only: there is one current summary
    # report per video, not separate rows per report_type variant.
    report = db.query(VideoReport).filter(VideoReport.video_id == video_uuid).first()
    if report is None:
        report = VideoReport(
            video_id=video_uuid,
            report_type=SUMMARY_REPORT_TYPE,
            title=video.title,
            html_content=html,
            artifact_path=str(artifact_path),
        )
        db.add(report)
    report.report_type = SUMMARY_REPORT_TYPE
    report.title = video.title
    report.html_content = html
    report.markdown_content = markdown
    report.artifact_path = str(artifact_path)
    report.model = summary.model if summary else None
    report.prompt_tokens = summary.prompt_tokens if summary else None
    report.completion_tokens = summary.completion_tokens if summary else None
    report.delivery_status = "pending"
    report.delivery_error = None

    if commit:
        db.commit()
        db.refresh(report)
    else:
        db.flush()

    logger.info("video_report_generated", video_id=str(video_uuid), artifact_path=str(artifact_path))
    return report


__all__ = [
    "ReportSection",
    "ReportRenderData",
    "ReportQualityError",
    "build_report_caption",
    "build_report_render_data",
    "generate_video_report",
    "markdownish_to_safe_html",
    "render_video_report_html",
    "render_video_report_markdown",
]
