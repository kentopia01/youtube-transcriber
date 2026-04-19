"""Post-process LLM chat responses into Perplexity-style output.

Given the raw LLM content + the list of retrieved source chunks, this module:

1. Parses citation markers the LLM emitted — supports several forms the
   model is known to produce:
      - ``[1]`` or ``[1, 2]``           (pure chunk indices)
      - ``[1 0:42]`` / ``[1 19:07 - 19:51]``  (index + timestamp)
      - ``[19:07 - 19:51]`` / ``[0:42]`` (timestamp only)
2. Collapses all citations in a paragraph to one or two compact chip links
   at the end of the paragraph.
3. Renders each chip as Telegram-friendly Markdown:
      ``[▶ Video Title · 19:07](https://youtu.be/VIDEOID?t=1147)``
   (or ``📄 Title · Summary`` for summary-chunk sources)

Fail-open: if the raw response can't be parsed, it is returned unchanged
so a brittle regex never mangles a working answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


CITATION_BRACKET_RE = re.compile(r"\[([^\[\]\n]{1,80})\]")
_IDX_ONLY_RE = re.compile(r"^\s*\d+(?:\s*,\s*\d+)*\s*$")
_IDX_WITH_TS_RE = re.compile(
    r"^\s*(\d+)\s+(\d+:\d+(?::\d+)?)(?:\s*-\s*(\d+:\d+(?::\d+)?))?\s*$"
)
_TS_ONLY_RE = re.compile(
    r"^\s*(\d+:\d+(?::\d+)?)(?:\s*-\s*(\d+:\d+(?::\d+)?))?\s*$"
)


def _parse_timestamp(s: str) -> int:
    parts = [int(p) for p in s.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0


def _fmt_timestamp(seconds: int | float | None) -> str:
    if seconds is None:
        return "—"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


@dataclass(frozen=True)
class _ChipKey:
    """Dedupe key — the same chunk referenced twice in a paragraph collapses."""

    video_id: str
    start_time_bucket: int  # rounded to 15s to collapse near-duplicates


def _find_source_by_index(index: int, sources: list[dict]) -> dict | None:
    if 1 <= index <= len(sources):
        return sources[index - 1]
    return None


def _find_source_by_timestamp(seconds: int, sources: list[dict]) -> dict | None:
    """Match a bare timestamp citation back to the chunk whose window contains it."""
    candidates = []
    for src in sources:
        start = src.get("start_time")
        end = src.get("end_time")
        if start is None:
            continue
        s = int(start)
        e = int(end) if end is not None else s + 600
        if s <= seconds <= e:
            candidates.append((abs(seconds - s), src))
    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]
    return None


def _chip_for_source(src: dict, *, ts_seconds: int | None = None) -> tuple[_ChipKey, str]:
    """Return (dedupe_key, markdown_link_text)."""
    video_id_full = str(src.get("video_id") or "")
    title = (src.get("video_title") or "source").strip()
    # Shorten very long titles so chips stay compact.
    if len(title) > 60:
        title = title[:57].rstrip() + "…"

    source_type = src.get("source_type") or "transcript"
    start = src.get("start_time")
    if ts_seconds is None:
        ts_seconds = int(start) if start is not None else None

    yt_id = _extract_youtube_id(src)

    if source_type == "summary":
        url = f"https://youtu.be/{yt_id}" if yt_id else "#"
        return (_ChipKey(video_id_full, -1), f"[📄 {title} · Summary]({url})")

    if yt_id and ts_seconds is not None:
        url = f"https://youtu.be/{yt_id}?t={ts_seconds}"
    elif yt_id:
        url = f"https://youtu.be/{yt_id}"
    else:
        url = "#"

    label = f"▶ {title} · {_fmt_timestamp(ts_seconds)}"
    bucket = (ts_seconds // 15) if ts_seconds is not None else 0
    return (_ChipKey(video_id_full, bucket), f"[{label}]({url})")


def _extract_youtube_id(src: dict) -> str | None:
    """Resolve the 11-char YouTube ID from the source row.

    The chat service's source dicts carry a UUID ``video_id`` (our DB id),
    not the YouTube id. Call sites that want proper video links must also
    include ``youtube_video_id``; fall back to nothing when absent.
    """
    yt = src.get("youtube_video_id") or src.get("yt_video_id")
    if yt:
        return str(yt)
    return None


def _parse_bracket_body(body: str, sources: list[dict]) -> list[tuple[_ChipKey, str]]:
    """Resolve a single ``[...]`` body into zero-or-more chips."""
    body = body.strip()

    if _IDX_ONLY_RE.match(body):
        chips: list[tuple[_ChipKey, str]] = []
        for raw in re.split(r"\s*,\s*", body):
            try:
                idx = int(raw)
            except ValueError:
                continue
            src = _find_source_by_index(idx, sources)
            if src:
                chips.append(_chip_for_source(src))
        return chips

    m = _IDX_WITH_TS_RE.match(body)
    if m:
        idx = int(m.group(1))
        ts = _parse_timestamp(m.group(2))
        src = _find_source_by_index(idx, sources)
        if src:
            return [_chip_for_source(src, ts_seconds=ts)]
        return []

    m = _TS_ONLY_RE.match(body)
    if m:
        ts = _parse_timestamp(m.group(1))
        src = _find_source_by_timestamp(ts, sources)
        if src:
            return [_chip_for_source(src, ts_seconds=ts)]
        return []

    return []


def _process_paragraph(paragraph: str, sources: list[dict]) -> str:
    """Replace every ``[...]`` inside a paragraph with an empty string, collect
    the resolved chips, then append them at the paragraph end."""
    collected: list[tuple[_ChipKey, str]] = []

    def replace(match: re.Match) -> str:
        body = match.group(1)
        chips = _parse_bracket_body(body, sources)
        if not chips:
            # Leave unparseable brackets (e.g. "[Summary]") in place.
            return match.group(0)
        collected.extend(chips)
        return ""  # strip inline citation; we'll place chips at the end

    stripped = CITATION_BRACKET_RE.sub(replace, paragraph)
    # Clean up spacing left by stripped citations
    stripped = re.sub(r"[ \t]+([,.;:!?])", r"\1", stripped)
    stripped = re.sub(r"[ \t]{2,}", " ", stripped)
    stripped = stripped.strip()

    if not collected:
        return stripped

    # Dedupe preserving order
    seen: set[_ChipKey] = set()
    unique_chips: list[str] = []
    for key, chip in collected:
        if key in seen:
            continue
        seen.add(key)
        unique_chips.append(chip)

    chips_inline = " · ".join(unique_chips[:3])  # cap 3 chips per paragraph
    if stripped and not stripped.endswith((".", "?", "!", ":", ")")):
        return f"{stripped} {chips_inline}"
    return f"{stripped} {chips_inline}".strip()


def format_response(content: str, sources: list[dict]) -> str:
    """Transform LLM-generated content into chip-formatted output.

    ``sources`` must be the list returned by ``chat_with_context``. Each row
    should include at minimum: ``video_id``, ``video_title``, ``start_time``,
    ``end_time``, and ideally ``youtube_video_id`` so chips can link to the
    exact YouTube timestamp.
    """
    if not content:
        return content
    try:
        paragraphs = content.split("\n\n")
        rendered = [_process_paragraph(p, sources) for p in paragraphs]
        return "\n\n".join(rendered).strip()
    except Exception:  # noqa: BLE001 — fail-open, never break a working answer
        return content


__all__ = ["format_response"]
