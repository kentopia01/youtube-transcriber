"""Small markdown helpers for scan-first summaries.

These helpers intentionally support only the markdown shape this project emits:
headings, unordered bullets, ordered bullets, and plain paragraphs. Keeping them
small avoids adding a renderer dependency to validation/report delivery paths.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.+?)\s*$")
BULLET_PREFIX_PATTERN = re.compile(r"^(?:[-*]\s+|\d+[.)]\s+)")


def normalize_heading(text: str) -> str:
    """Normalize a markdown/html-ish heading for permissive section matching."""
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"[*_`#>\"']", "", text).strip().lower()
    text = text.replace("&", "and")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def extract_heading_sections(markdown: str | None) -> dict[str, str]:
    """Extract sections keyed by normalized markdown heading text."""
    if not markdown:
        return {}

    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in markdown.strip().splitlines():
        heading_match = HEADING_PATTERN.match(raw.strip())
        if heading_match:
            current = normalize_heading(heading_match.group(1))
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(raw.rstrip())

    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def find_section(sections: Mapping[str, str], heading: str) -> str | None:
    """Return a section by human heading name from normalized section mapping."""
    return sections.get(normalize_heading(heading))


def extract_markdown_section(markdown: str | None, headings: Sequence[str]) -> str | None:
    """Return markdown content under the first matching heading."""
    if not markdown:
        return None

    wanted = {normalize_heading(heading) for heading in headings}
    lines = markdown.strip().splitlines()
    collecting = False
    heading_level: int | None = None
    collected: list[str] = []

    for raw in lines:
        stripped = raw.strip()
        heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            normalized = normalize_heading(heading_match.group(2))
            if collecting and heading_level is not None and level <= heading_level:
                break
            if normalized in wanted:
                collecting = True
                heading_level = level
                collected = []
                continue
        if collecting:
            collected.append(raw.rstrip())

    content = "\n".join(collected).strip()
    if content:
        return content

    sections = extract_heading_sections(markdown)
    for heading in headings:
        content = find_section(sections, heading)
        if content:
            return content
    return None


def first_content_block(markdown: str | None, *, max_lines: int = 4) -> str | None:
    """Return the first non-heading content block as a fallback scan excerpt."""
    if not markdown:
        return None

    lines: list[str] = []
    for raw in markdown.strip().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line in {"---", "***"}:
            if lines:
                break
            continue
        lines.append(raw.rstrip())
        if len(lines) >= max_lines:
            break

    content = "\n".join(lines).strip()
    return content or None


def count_bullets(markdown: str | None) -> int:
    """Count unordered or ordered markdown bullets in a block."""
    if not markdown:
        return 0
    return sum(1 for raw in markdown.splitlines() if BULLET_PREFIX_PATTERN.match(raw.strip()))


def bullet_points_from_markdown(markdown: str | None, *, limit: int) -> list[str]:
    """Extract bullet text from a markdown block."""
    if not markdown:
        return []

    points: list[str] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if BULLET_PREFIX_PATTERN.match(line):
            points.append(BULLET_PREFIX_PATTERN.sub("", line))
        if len(points) >= limit:
            break
    return points


__all__ = [
    "bullet_points_from_markdown",
    "count_bullets",
    "extract_heading_sections",
    "extract_markdown_section",
    "find_section",
    "first_content_block",
    "normalize_heading",
]
