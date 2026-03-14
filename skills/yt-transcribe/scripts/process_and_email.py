#!/usr/bin/env python3
"""Route YouTube video vs channel/profile URLs through the local transcriber,
wait for completion, and optionally send a fixed-template email as Nora.

This is the **canonical** script for the yt-transcribe workflow.
The OpenClaw skill wrapper (yt-transcribe-email) delegates to this file.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import error, parse, request

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 3600
DEFAULT_POLL_SECONDS = 5
DEFAULT_CHANNEL_LIMIT = 5
NORA_ACCOUNT = "nora@01-digital.com"

# Default recipient map; overridden by config file or env var
_DEFAULT_RECIPIENT_MAP: dict[str, str] = {
    "me": "kenneth@01-digital.com",
    "ken": "kenneth@01-digital.com",
    "self": "kenneth@01-digital.com",
}

# Retry settings for HTTP requests
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1.0
BACKOFF_MULTIPLIER = 2.0


@dataclass
class VideoResult:
    title: str
    source_url: str
    app_video_id: str
    job_id: str
    status: str
    summary: str | None
    transcript: str | None
    language: str | None
    speakers: list[str] = field(default_factory=list)


class ApiError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Config-driven recipient mapping
# ---------------------------------------------------------------------------

def _load_recipient_map() -> dict[str, str]:
    """Load recipient aliases.  Priority:
    1. $YT_RECIPIENT_MAP env var (JSON string, e.g. '{"me":"a@b.com"}')
    2. ~/.yt-transcriber-recipients.json file
    3. Built-in defaults
    """
    # env var
    env_val = os.environ.get("YT_RECIPIENT_MAP")
    if env_val:
        try:
            parsed = json.loads(env_val)
            if isinstance(parsed, dict):
                return {k.lower(): v for k, v in parsed.items()}
        except (json.JSONDecodeError, TypeError):
            print(f"Warning: YT_RECIPIENT_MAP env var is not valid JSON, using defaults", file=sys.stderr)

    # config file
    config_path = Path.home() / ".yt-transcriber-recipients.json"
    if config_path.is_file():
        try:
            with open(config_path) as f:
                parsed = json.load(f)
            if isinstance(parsed, dict):
                return {k.lower(): v for k, v in parsed.items()}
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Warning: Could not read {config_path}: {exc}", file=sys.stderr)

    return dict(_DEFAULT_RECIPIENT_MAP)


def resolve_recipient(value: str | None) -> str | None:
    """Resolve a recipient alias (e.g. 'me') to an email address."""
    if not value:
        return None
    recipient_map = _load_recipient_map()
    mapped = recipient_map.get(value.lower())
    if mapped:
        return mapped
    # If it looks like an email, pass through
    return value


# ---------------------------------------------------------------------------
# HTTP helpers with retry + exponential backoff
# ---------------------------------------------------------------------------

def http_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    max_retries: int = MAX_RETRIES,
    initial_backoff: float = INITIAL_BACKOFF_SECONDS,
) -> Any:
    """Make an HTTP request with retry/backoff for transient failures."""
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    last_exc: Exception | None = None
    backoff = initial_backoff

    for attempt in range(max_retries + 1):
        req = request.Request(url, data=data, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else None
        except error.HTTPError as exc:
            # Don't retry client errors (4xx) except 429
            if 400 <= exc.code < 500 and exc.code != 429:
                try:
                    detail = exc.read().decode("utf-8")
                except Exception:
                    detail = str(exc)
                raise ApiError(f"{method} {url} failed: HTTP {exc.code}: {detail}") from exc
            last_exc = exc
        except (error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc

        if attempt < max_retries:
            time.sleep(backoff)
            backoff *= BACKOFF_MULTIPLIER

    # Exhausted retries
    if isinstance(last_exc, error.HTTPError):
        try:
            detail = last_exc.read().decode("utf-8")
        except Exception:
            detail = str(last_exc)
        raise ApiError(f"{method} {url} failed after {max_retries + 1} attempts: HTTP {last_exc.code}: {detail}") from last_exc
    raise ApiError(f"{method} {url} failed after {max_retries + 1} attempts: {last_exc}") from last_exc


# ---------------------------------------------------------------------------
# URL classification
# ---------------------------------------------------------------------------

def is_playlist_url(url: str) -> bool:
    """Return True for pure playlist URLs (no video ID present)."""
    parsed = parse.urlparse(url)
    host = (parsed.netloc or "").lower()
    if "youtube.com" not in host:
        return False
    path = parsed.path or ""
    qs = parse.parse_qs(parsed.query)
    # Pure playlist page: /playlist?list=...
    if path.rstrip("/") == "/playlist" and "list" in qs:
        return True
    return False


def strip_playlist_params(url: str) -> str:
    """Remove &list= and &index= query params from a video URL.

    When a user copies a URL like watch?v=abc&list=PLxxx&index=3,
    we want to treat it as a single video, not a playlist.
    """
    parsed = parse.urlparse(url)
    qs = parse.parse_qs(parsed.query, keep_blank_values=True)
    qs.pop("list", None)
    qs.pop("index", None)
    new_query = parse.urlencode(qs, doseq=True)
    return parse.urlunparse(parsed._replace(query=new_query))


def is_channel_url(url: str) -> bool:
    parsed = parse.urlparse(url)
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    if "youtube.com" not in host:
        return False
    return path.startswith("/@") or path.startswith("/channel/") or path.startswith("/c/") or path.startswith("/user/")


# ---------------------------------------------------------------------------
# API wrappers
# ---------------------------------------------------------------------------

def submit_video(base_url: str, url: str) -> dict[str, Any]:
    return http_json("POST", f"{base_url}/api/videos", {"url": url})


def get_job(base_url: str, job_id: str) -> dict[str, Any]:
    return http_json("GET", f"{base_url}/api/jobs/{job_id}")


def get_transcription(base_url: str, app_video_id: str) -> dict[str, Any]:
    return http_json("GET", f"{base_url}/api/transcriptions/{app_video_id}")


def discover_channel(base_url: str, url: str, limit: int) -> dict[str, Any]:
    return http_json("POST", f"{base_url}/api/channels", {"url": url, "limit": limit})


def fetch_video_title_fallback(url: str) -> str | None:
    try:
        oembed_url = "https://www.youtube.com/oembed?format=json&url=" + parse.quote(url, safe="")
        data = http_json("GET", oembed_url, max_retries=1)
        if isinstance(data, dict):
            title = data.get("title")
            if isinstance(title, str) and title.strip():
                return title.strip()
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# Job polling
# ---------------------------------------------------------------------------

def wait_for_job(base_url: str, job_id: str, timeout: int, poll_seconds: int) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = get_job(base_url, job_id)
        status = job.get("status")
        if status in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(poll_seconds)
    raise TimeoutError(f"Timed out waiting for job {job_id}")


# ---------------------------------------------------------------------------
# Video / channel collection
# ---------------------------------------------------------------------------

def collect_video(base_url: str, url: str, timeout: int, poll_seconds: int, title_hint: str | None = None) -> VideoResult:
    submission = submit_video(base_url, url)
    job_id = submission["job_id"]
    app_video_id = submission["video_id"]
    job = wait_for_job(base_url, job_id, timeout=timeout, poll_seconds=poll_seconds)
    status = job.get("status", "unknown")

    if status != "completed":
        fallback_title = title_hint or job.get("video_title") or job.get("title") or fetch_video_title_fallback(url) or "YouTube Video"
        return VideoResult(
            title=fallback_title,
            source_url=url,
            app_video_id=app_video_id,
            job_id=job_id,
            status=status,
            summary="Unavailable",
            transcript=job.get("error_message") or "No transcript available.",
            language=None,
            speakers=[],
        )

    tx = get_transcription(base_url, app_video_id)
    resolved_title = title_hint or tx.get("video_title") or tx.get("title") or job.get("video_title") or job.get("title") or fetch_video_title_fallback(url) or "YouTube Video"
    return VideoResult(
        title=resolved_title,
        source_url=url,
        app_video_id=app_video_id,
        job_id=job_id,
        status=status,
        summary=tx.get("summary") or "No summary available.",
        transcript=tx.get("full_text") or "No transcript available.",
        language=tx.get("language_detected") or tx.get("language"),
        speakers=tx.get("speakers") or [],
    )


def collect_channel(base_url: str, url: str, limit: int, timeout: int, poll_seconds: int) -> tuple[str | None, list[VideoResult]]:
    discovery = discover_channel(base_url, url, limit)
    channel_name = discovery.get("channel_name") or None
    videos = discovery.get("videos") or []

    if not videos:
        print(f"No videos discovered for channel URL: {url}", file=sys.stderr)
        return channel_name, []

    results: list[VideoResult] = []
    for item in videos[:limit]:
        video_url = item.get("url")
        if video_url and video_url.startswith("/"):
            video_url = f"https://www.youtube.com{video_url}"
        if not video_url:
            vid = item.get("video_id")
            video_url = f"https://www.youtube.com/watch?v={vid}"
        results.append(
            collect_video(base_url, video_url, timeout=timeout, poll_seconds=poll_seconds, title_hint=item.get("title"))
        )
    return channel_name, results


# ---------------------------------------------------------------------------
# Email templates
# ---------------------------------------------------------------------------

TEXT_EMAIL_TEMPLATE = """Hi,

Here's your YouTube summary from Nora.

Source URL: {source_url}
{channel_line}
Items processed: {item_count}

{items}

—
Nora
"""

TEXT_ITEM_TEMPLATE = """[{index}] {title}
Status: {status}
Open on YouTube: {video_url}{language_line}{speakers_line}

Summary:
{summary}
{transcript_section}"""

HTML_EMAIL_TEMPLATE = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{subject}</title>
    <style>
      body, table, td, div, p, a {{ -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }}
      p {{ margin: 0 0 12px 0; }}
      ul {{ margin: 10px 0 10px 20px; padding: 0; }}
      li {{ margin: 0 0 8px 0; }}
      h2, h3, h4 {{ margin: 0 0 10px 0; color:#1a1a2e; font-family: 'Playfair Display', Georgia, serif; }}
      code {{ font-family: 'JetBrains Mono', 'SFMono-Regular', monospace; background:#f9fafb; padding:2px 5px; border-radius:4px; font-size: 0.95em; }}
      strong {{ color:#1a1a2e; }}
      em {{ color:#4a5568; }}
    </style>
  </head>
  <body style="margin:0;padding:0;background:#f5f6f7;color:#1a1a2e;font-family:Inter,Arial,sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f5f6f7;padding:10px 4px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:920px;background:#ffffff;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden;">
            <tr>
              <td style="background:#1a1a2e;padding:18px 20px;color:#ffffff;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    <td align="left" style="font-family:'Playfair Display',Georgia,serif;font-size:26px;font-weight:700;line-height:1.2;">YT Transcriber</td>
                    <td align="right"><span style="display:inline-block;background:rgba(244,129,32,0.2);color:#ffffff;border:1px solid rgba(244,129,32,0.35);padding:6px 12px;border-radius:999px;font-size:11px;font-weight:600;">Nora</span></td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr><td style="padding:0 18px 18px 18px;">{channel_block}{items_html}</td></tr>
            <tr>
              <td style="padding:0 18px 18px 18px;">
                <div style="border:1px solid #f0f1f3;border-radius:12px;background:#f9fafb;padding:14px 16px;font-size:12px;line-height:1.6;color:#4a5568;">Sent by Nora @ 01-digital via youtube-transcriber.</div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

HTML_ITEM_TEMPLATE = """<div style="margin-bottom:12px;border:1px solid #e5e7eb;border-radius:14px;background:#ffffff;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.04);">
  <div style="height:3px;background:#f48120;font-size:0;line-height:0;">&nbsp;</div>
  <div style="padding:14px 14px 12px 14px;">
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">
      <div>
        <div style="font-family:'Playfair Display',Georgia,serif;font-size:23px;line-height:1.2;color:#1a1a2e;font-weight:700;">{title}</div>
        <div style="margin-top:8px;font-size:14px;line-height:1.7;color:#4a5568;"><a href="{video_url_attr}" style="color:#f48120;text-decoration:none;">Open on YouTube</a></div>
      </div>
    </div>
    {meta_block}
    <div style="margin-top:14px;border:1px solid #f0f1f3;border-radius:12px;background:#f9fafb;padding:14px 16px;">
      <div style="font-family:'JetBrains Mono','SFMono-Regular',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:#9ca3af;">Summary</div>
      <div style="margin-top:8px;font-size:14px;line-height:1.65;color:#4a5568;">{summary}</div>
    </div>
    {transcript_block}
  </div>
</div>
"""

HTML_TRANSCRIPT_BLOCK = """<div style="margin-top:14px;border:1px solid #f0f1f3;border-radius:12px;background:#f9fafb;padding:14px 16px;">
      <div style="font-family:'JetBrains Mono','SFMono-Regular',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:#9ca3af;">Full Transcript</div>
      <div style="margin-top:8px;font-size:13px;line-height:1.65;color:#4a5568;">{transcript}</div>
    </div>"""


# ---------------------------------------------------------------------------
# HTML rendering helpers
# ---------------------------------------------------------------------------

def render_status_badge(status: str) -> str:
    styles = {
        "completed": ("#16a34a", "rgba(22,163,74,0.08)"),
        "failed": ("#dc2626", "rgba(220,38,38,0.08)"),
        "cancelled": ("#9ca3af", "#f9fafb"),
        "queued": ("#2563eb", "rgba(37,99,235,0.08)"),
        "pending": ("#4a5568", "#f9fafb"),
    }
    fg, bg = styles.get(status, ("#d97706", "rgba(217,119,6,0.08)"))
    return (
        f'<span style="display:inline-block;padding:7px 13px;border-radius:999px;'
        f'background:{bg};color:{fg};font-size:13px;font-weight:700;text-transform:capitalize;">{html.escape(status)}</span>'
    )


def markdownish_to_html(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return "<p>No content available.</p>"

    lines = text.split("\n")
    blocks: list[str] = []
    paragraph: list[str] = []
    in_list = False

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            content = " ".join(part.strip() for part in paragraph if part.strip())
            blocks.append(f"<p>{inline_markdown_to_html(content)}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            blocks.append("</ul>")
            in_list = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            close_list()
            continue
        if stripped.startswith(("- ", "* ")):
            flush_paragraph()
            if not in_list:
                blocks.append("<ul>")
                in_list = True
            blocks.append(f"<li>{inline_markdown_to_html(stripped[2:].strip())}</li>")
            continue
        if re.match(r"^#{1,3}\s+", stripped):
            flush_paragraph()
            close_list()
            level = len(stripped) - len(stripped.lstrip("#"))
            level = min(level, 3)
            content = stripped[level:].strip()
            blocks.append(f"<h{level+1}>{inline_markdown_to_html(content)}</h{level+1}>")
            continue
        paragraph.append(stripped)

    flush_paragraph()
    close_list()
    return "\n".join(blocks)


def inline_markdown_to_html(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2" style="color:#f48120;text-decoration:none;">\1</a>', escaped)
    return escaped


# ---------------------------------------------------------------------------
# Email body builders
# ---------------------------------------------------------------------------

def build_subject(source_url: str, channel_name: str | None, results: list[VideoResult]) -> str:
    if len(results) == 1:
        subtitle = (results[0].summary or "").strip().splitlines()[0] if results[0].summary else ""
        subtitle = re.sub(r"\s+", " ", subtitle).strip()
        clean_subtitle = re.sub(r"^#+\s*", "", subtitle).strip()
        if clean_subtitle:
            clean_subtitle = clean_subtitle[:90] + ("..." if len(clean_subtitle) > 90 else "")
            return f"Youtube Transcript: {clean_subtitle}"
        return "Youtube Transcript"
    if channel_name:
        return f"Youtube Transcript: {channel_name}"
    return "Youtube Transcript"


def build_text_body(
    source_url: str,
    channel_name: str | None,
    results: list[VideoResult],
    *,
    include_transcript: bool = False,
) -> str:
    item_blocks = []
    for idx, item in enumerate(results, start=1):
        transcript_section = ""
        if include_transcript and item.transcript:
            transcript_section = f"\nTranscript:\n{item.transcript.strip()}\n"

        item_blocks.append(
            TEXT_ITEM_TEMPLATE.format(
                index=idx,
                title=item.title,
                status=item.status,
                video_url=item.source_url,
                language_line=f"\nLanguage: {item.language}" if item.language else "",
                speakers_line=f"\nSpeakers: {', '.join(item.speakers)}" if item.speakers else "",
                summary=(item.summary or "No summary available.").strip(),
                transcript_section=transcript_section,
            ).strip()
        )

    return TEXT_EMAIL_TEMPLATE.format(
        source_url=source_url,
        channel_line=f"Channel: {channel_name}" if channel_name else "",
        item_count=len(results),
        items="\n\n" + ("\n\n" + ("-" * 72) + "\n\n").join(item_blocks),
    ).strip() + "\n"


def build_html_body(
    subject: str,
    source_url: str,
    channel_name: str | None,
    results: list[VideoResult],
    *,
    include_transcript: bool = False,
) -> str:
    items_html = []
    for item in results:
        meta_parts = []
        if item.language:
            meta_parts.append(("Language", html.escape(item.language)))
        if item.speakers:
            meta_parts.append(("Speakers", html.escape(", ".join(item.speakers))))

        meta_block = ""
        if meta_parts:
            chips = "".join(
                f'<span style="display:inline-block;margin:10px 8px 0 0;padding:6px 10px;border:1px solid #e5e7eb;border-radius:999px;background:#ffffff;color:#4a5568;font-size:11px;"><strong style="color:#1a1a2e;">{label}:</strong> {value}</span>'
                for label, value in meta_parts
            )
            meta_block = f'<div style="margin-top:6px;">{chips}</div>'

        transcript_block = ""
        if include_transcript and item.transcript:
            transcript_block = HTML_TRANSCRIPT_BLOCK.format(
                transcript=markdownish_to_html(item.transcript.strip())
            )

        items_html.append(
            HTML_ITEM_TEMPLATE.format(
                title=html.escape(item.title),
                video_url_attr=html.escape(item.source_url, quote=True),
                status_badge=render_status_badge(item.status),
                meta_block=meta_block,
                summary=markdownish_to_html((item.summary or "No summary available.").strip()),
                transcript_block=transcript_block,
            )
        )

    channel_block = ""
    if channel_name:
        channel_block = (
            '<div style="margin-top:16px;border:1px solid #e5e7eb;border-radius:12px;background:#ffffff;padding:14px 16px;">'
            '<div style="font-family:\'JetBrains Mono\',\'SFMono-Regular\',monospace;font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:#9ca3af;">Channel</div>'
            f'<div style="margin-top:6px;font-size:14px;line-height:1.5;color:#1a1a2e;">{html.escape(channel_name)}</div>'
            "</div>"
        )

    return HTML_EMAIL_TEMPLATE.format(
        subject=html.escape(subject),
        source_url_attr=html.escape(source_url, quote=True),
        source_url_html=html.escape(source_url),
        item_count=len(results),
        channel_block=channel_block,
        items_html="".join(items_html),
    )


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

def send_email(recipient: str, subject: str, text_body: str, html_body: str) -> None:
    """Send email via gog CLI. Temp files are cleaned up after use."""
    text_path = None
    html_path = None
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as text_fh:
            text_fh.write(text_body)
            text_path = text_fh.name
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".html") as html_fh:
            html_fh.write(html_body)
            html_path = html_fh.name

        cmd = [
            "gog", "gmail", "send",
            "--account", NORA_ACCOUNT,
            "--to", recipient,
            "--subject", subject,
            "--body-file", text_path,
            "--body-html-file", html_path,
        ]
        subprocess.run(cmd, check=True)
    finally:
        for path in (text_path, html_path):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def init_recipient_config() -> str:
    """Create ~/.yt-transcriber-recipients.json with defaults if it doesn't exist.
    Returns the path to the config file."""
    config_path = Path.home() / ".yt-transcriber-recipients.json"
    if config_path.is_file():
        return f"Config already exists: {config_path}"
    config_path.write_text(json.dumps(_DEFAULT_RECIPIENT_MAP, indent=2) + "\n")
    return f"Created recipient config: {config_path}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Route a YouTube URL through the transcriber and optionally email the result.")
    p.add_argument("url", nargs="?", help="YouTube video or channel/profile URL")
    p.add_argument("--to", help="Recipient email. Use 'me' to send to Ken (configurable).")
    p.add_argument("--send", action="store_true", help="Actually send the email via gog as Nora")
    p.add_argument("--include-transcript", action="store_true", help="Include full transcript in email (default: summary only)")
    p.add_argument("--channel-limit", type=int, default=DEFAULT_CHANNEL_LIMIT, help="Max videos to process for a channel/profile URL")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    p.add_argument("--pretty", action="store_true")
    p.add_argument("--init-recipients", action="store_true", help="Create ~/.yt-transcriber-recipients.json with defaults and exit")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # --init-recipients: bootstrap config file and exit
    if args.init_recipients:
        msg = init_recipient_config()
        print(msg)
        return 0

    if not args.url:
        print("Error: url is required (unless using --init-recipients)", file=sys.stderr)
        return 1

    recipient = resolve_recipient(args.to)

    # Reject pure playlist URLs explicitly
    if is_playlist_url(args.url):
        print(
            f"Error: Playlist URLs are not supported. Please provide a single video URL or a channel/profile URL.\n"
            f"  Given: {args.url}\n"
            f"  Tip: To transcribe a specific video from a playlist, use its direct watch URL (e.g. https://www.youtube.com/watch?v=VIDEO_ID)",
            file=sys.stderr,
        )
        return 1

    # Strip playlist params from video URLs (watch?v=abc&list=PLxxx → watch?v=abc)
    url = strip_playlist_params(args.url)

    if is_channel_url(url):
        channel_name, results = collect_channel(args.base_url, url, args.channel_limit, args.timeout, args.poll_seconds)
        mode = "channel"
        if not results:
            print(f"No videos found for channel URL: {url}", file=sys.stderr)
            payload = {
                "mode": mode,
                "source_url": url,
                "recipient": recipient,
                "sent": False,
                "subject": "Youtube Transcript: No videos found",
                "body": f"No videos were discovered for the channel URL: {url}\n",
                "videos": [],
            }
            json.dump(payload, sys.stdout, indent=2 if args.pretty else None)
            sys.stdout.write("\n")
            return 0
    else:
        channel_name = None
        results = [collect_video(args.base_url, url, args.timeout, args.poll_seconds)]
        mode = "video"

    include_transcript = args.include_transcript
    subject = build_subject(url, channel_name, results)
    body = build_text_body(url, channel_name, results, include_transcript=include_transcript)
    html_body = build_html_body(subject, url, channel_name, results, include_transcript=include_transcript)

    if args.send:
        if not recipient:
            raise SystemExit("--send requires --to <email|me>")
        send_email(recipient, subject, body, html_body)

    payload = {
        "mode": mode,
        "source_url": url,
        "recipient": recipient,
        "sent": bool(args.send and recipient),
        "subject": subject,
        "body": body,
        "html_body": html_body,
        "videos": [
            {
                "title": v.title,
                "source_url": v.source_url,
                "status": v.status,
                "summary": v.summary,
                "transcript": v.transcript if include_transcript else None,
                "language": v.language,
                "speakers": v.speakers,
                "job_id": v.job_id,
                "app_video_id": v.app_video_id,
            }
            for v in results
        ],
    }
    json.dump(payload, sys.stdout, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
