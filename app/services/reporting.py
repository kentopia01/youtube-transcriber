"""Styled per-video report generation.

This module intentionally renders deterministic HTML from already-persisted
transcript and summary data. The report is a delivery artifact, not a new
pipeline truth source; failures here should never make a completed transcript
look failed.
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
from app.models.video_report import VideoReport

logger = structlog.get_logger()


@dataclass
class ReportRenderData:
    title: str
    published_date: str | None
    channel_name: str | None
    video_url: str | None
    duration: str | None
    executive_summary_html: str
    key_points: list[str]
    generated_at: str
    word_count: int | None = None
    model: str | None = None


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


def _inline_markdown(text: str) -> str:
    escaped = escape(text, quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def _key_points_from_summary(summary: str | None, *, limit: int = 6) -> list[str]:
    if not summary:
        return []
    points: list[str] = []
    for raw in summary.splitlines():
        line = raw.strip()
        if line.startswith(("- ", "* ")):
            points.append(re.sub(r"^[-*]\s+", "", line))
        elif re.match(r"^\d+\.\s+", line):
            points.append(re.sub(r"^\d+\.\s+", "", line))
        if len(points) >= limit:
            break
    if points:
        return points
    sentences = re.split(r"(?<=[.!?])\s+", summary.strip())
    return [s for s in sentences if s][:limit]


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
        executive_summary_html=_markdownish_to_html(summary_text),
        key_points=_key_points_from_summary(summary_text),
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
    lines.append("## Executive Summary")
    # Keep markdown artifact simple/plain; HTML is the canonical styled artifact.
    lines.append(re.sub(r"<[^>]+>", "", data.executive_summary_html))
    if data.key_points:
        lines.extend(["", "## Key Points"])
        lines.extend(f"- {p}" for p in data.key_points)
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

    report = db.query(VideoReport).filter(VideoReport.video_id == video_uuid).first()
    if report is None:
        report = VideoReport(video_id=video_uuid, title=video.title, html_content=html, artifact_path=str(artifact_path))
        db.add(report)
    report.report_type = "summary_report"
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
    "ReportRenderData",
    "build_report_render_data",
    "generate_video_report",
    "render_video_report_html",
    "render_video_report_markdown",
]
