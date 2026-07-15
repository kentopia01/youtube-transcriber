"""Deterministic guardrails for T015 scan-first summaries.

This module is intentionally pure: it checks the markdown contract produced by
summarization/backfill flows and returns warnings/errors for operators. It does
not call an LLM and does not persist anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.summary_markdown import (
    count_bullets,
    extract_heading_sections,
    extract_markdown_section,
    find_section,
    normalize_heading,
)

REQUIRED_HEADINGS: tuple[str, ...] = (
    "At-a-Glance",
    "Executive Summary",
    "Key Takeaways",
    "Notable Concepts & Terms",
    "Operator Notes / Why Ken Should Care",
    "Source/Metadata",
)

AT_A_GLANCE_HEADINGS: tuple[str, ...] = (
    "At-a-Glance",
    "At a Glance",
    "30-second take",
    "30-second scan",
)
EXECUTIVE_SUMMARY_HEADINGS: tuple[str, ...] = (
    "Executive Summary",
    "Overall Summary",
    "Summary",
)
KEY_TAKEAWAY_HEADINGS: tuple[str, ...] = (
    "Key Takeaways",
    "Key takes",
    "Key points",
)
DETAILED_BRIEF_HEADINGS: tuple[str, ...] = (
    "Detailed Brief",
    "Useful details",
    "Details",
)
CONCEPT_HEADINGS: tuple[str, ...] = (
    "Notable Concepts & Terms",
    "Notable Concepts and Terms",
    "Terms",
)
OPERATOR_NOTE_HEADINGS: tuple[str, ...] = (
    "Operator Notes / Why Ken Should Care",
    "Operator Notes",
    "Why Ken Should Care",
    "Ken relevance",
    "Why it matters to Ken",
)
SOURCE_METADATA_HEADINGS: tuple[str, ...] = (
    "Source/Metadata",
    "Source Metadata",
    "Metadata",
)

WATCH_VERDICTS: tuple[str, ...] = ("Skip", "Skim", "Watch fully")
NORMAL_MIN_KEY_TAKES = 4
DEEP_MIN_KEY_TAKES = 5
LOW_CONTENT_MIN_KEY_TAKES = 2
DEEP_BRIEF_WORD_COUNT = 1500
DEEP_BRIEF_DURATION_SECONDS = 600
DEEP_MIN_EXECUTIVE_SUMMARY_CHARS = 240
DEEP_MIN_DETAILED_ITEMS = 1
DEEP_MIN_SUMMARY_CHARS = 1400

LOW_CONTENT_PATTERNS: tuple[str, ...] = (
    r"\blow[-\s]?content\s+(?:transcript|upload|video|source|summary|item)\b",
    r"\b(?:is|appears|seems|looks|reads as|flagged as)\s+(?:a\s+)?low[-\s]?content\b",
    r"\b(?:mostly|primarily|largely)\s+(?:music|lyrics|repetition|repeated text|repeated transcript|ads|placeholder text)\b",
    r"\b(?:music|lyrics|repetition|ads)\s+(?:only|with little substantive speech|with little substantive content)\b",
    r"\b(?:repeated|repetitive)\s+(?:text|transcript|lyrics|placeholder)\b",
    r"\bplaceholder\s+(?:upload|video|transcript|content|text)\b",
    r"\btoo little substantive\s+(?:speech|content|material)\b",
    r"\blittle substantive speech\b",
    r"\btranscript\s+(?:unavailable|invalid)\b",
    r"\binvalid transcript\b",
    r"\b(?:extraction|transcript)\s+failure\b",
)

LOW_CONTENT_NEGATION_PATTERNS: tuple[str, ...] = (
    r"\bnot\s+(?:a\s+)?low[-\s]?content\b",
    r"\bnot\s+(?:mostly|primarily|largely)\s+(?:music|lyrics|repetition|ads|placeholder text)\b",
    r"\bnot\s+(?:a\s+)?placeholder\b",
)

KEN_FOCUS_TERMS: tuple[str, ...] = (
    "agent",
    "agents",
    "ai ops",
    "ai operations",
    "automation",
    "workflow",
    "workflows",
    "content",
    "business",
    "opportunity",
    "opportunities",
    "investing",
    "investment",
    "gtm",
    "go to market",
    "go-to-market",
    "sales",
    "growth",
)

LOW_RELEVANCE_MARKERS: tuple[str, ...] = (
    "low relevance",
    "relevance is low",
    "limited relevance",
    "little relevance",
    "not especially relevant",
    "not directly relevant",
    "not applicable",
    "no clear relevance",
)

@dataclass(frozen=True)
class SummaryQualityResult:
    """Validation result for a generated scan-first summary."""

    missing_headings: tuple[str, ...]
    key_take_count: int
    minimum_key_takes: int
    watch_verdict: str | None
    ken_relevance: str | None
    is_low_content: bool
    requires_deep_brief: bool
    executive_summary_chars: int
    detailed_brief_item_count: int
    summary_chars: int
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.errors

    @property
    def is_malformed(self) -> bool:
        return bool(self.errors)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)


def _normalize_text(text: str | None) -> str:
    text = (text or "").lower()
    text = text.replace("&", "and")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _find_watch_verdict(markdown: str | None) -> str | None:
    text = markdown or ""
    verdict_line = re.search(
        r"\bverdict\s*[:\-]\s*(watch\s+fully|skim|skip)\b",
        text,
        flags=re.IGNORECASE,
    )
    if verdict_line:
        normalized = _normalize_text(verdict_line.group(1))
        if normalized == "watch fully":
            return "Watch fully"
        if normalized == "skim":
            return "Skim"
        if normalized == "skip":
            return "Skip"
    verdict_patterns = (
        ("Watch fully", r"\bwatch\s+fully\b"),
        ("Skim", r"\bskim\b"),
        ("Skip", r"\bskip\b"),
    )
    for verdict, pattern in verdict_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return verdict
    return None


def _find_any_section(
    sections: dict[str, str],
    headings: tuple[str, ...],
    *,
    markdown: str | None = None,
) -> str | None:
    content = extract_markdown_section(markdown, headings) if markdown else None
    if content:
        return content
    for heading in headings:
        content = find_section(sections, heading)
        if content is not None:
            return content
    return None


def _has_any_section(
    sections: dict[str, str],
    headings: tuple[str, ...],
    *,
    markdown: str | None = None,
) -> bool:
    content = _find_any_section(sections, headings, markdown=markdown)
    return bool(content and content.strip())


def _required_section_missing(
    sections: dict[str, str],
    required_heading: str,
    *,
    markdown: str | None = None,
) -> bool:
    aliases_by_required = {
        "At-a-Glance": AT_A_GLANCE_HEADINGS,
        "Executive Summary": EXECUTIVE_SUMMARY_HEADINGS,
        "Key Takeaways": KEY_TAKEAWAY_HEADINGS,
        "Detailed Brief": DETAILED_BRIEF_HEADINGS,
        "Notable Concepts & Terms": CONCEPT_HEADINGS,
        "Operator Notes / Why Ken Should Care": OPERATOR_NOTE_HEADINGS,
        "Source/Metadata": SOURCE_METADATA_HEADINGS,
    }
    return not _has_any_section(sections, aliases_by_required[required_heading], markdown=markdown)


def _is_explicit_low_content(summary: str | None) -> bool:
    text = summary or ""
    if not text.strip():
        return False
    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in LOW_CONTENT_NEGATION_PATTERNS):
        return False
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in LOW_CONTENT_PATTERNS)


def _mentions_ken_focus_or_low_relevance(ken_relevance: str | None) -> bool:
    normalized = _normalize_text(ken_relevance)
    if not normalized:
        return False
    return any(_normalize_text(term) in normalized for term in KEN_FOCUS_TERMS) or any(
        _normalize_text(term) in normalized for term in LOW_RELEVANCE_MARKERS
    )


def _requires_deep_brief(
    *,
    word_count: int | None = None,
    duration_seconds: float | None = None,
    is_low_content: bool = False,
) -> bool:
    if is_low_content:
        return False
    return bool(
        (word_count is not None and word_count >= DEEP_BRIEF_WORD_COUNT)
        or (duration_seconds is not None and duration_seconds >= DEEP_BRIEF_DURATION_SECONDS)
    )


def _bullet_lines(markdown: str | None) -> list[str]:
    if not markdown:
        return []
    return [
        re.sub(r"^(?:[-*]\s+|\d+[.)]\s+)", "", raw.strip())
        for raw in markdown.splitlines()
        if re.match(r"^(?:[-*]\s+|\d+[.)]\s+)", raw.strip())
    ]


def _count_detailed_items(markdown: str | None) -> int:
    if not markdown:
        return 0
    bullet_count = count_bullets(markdown)
    subheading_count = sum(1 for raw in markdown.splitlines() if re.match(r"^#{3,6}\s+", raw.strip()))
    paragraph_count = sum(
        1
        for raw in markdown.splitlines()
        if raw.strip()
        and not raw.strip().startswith("#")
        and not re.match(r"^(?:[-*]\s+|\d+[.)]\s+)", raw.strip())
    )
    return max(bullet_count, subheading_count, paragraph_count)


def _vague_key_take_errors(key_takes: str | None, *, expected_count: int) -> list[str]:
    bullets = _bullet_lines(key_takes)
    errors: list[str] = []
    vague_stems = (
        "discusses",
        "talks about",
        "covers",
        "mentions",
        "overview",
        "introduction to",
        "explores",
        "touches on",
    )
    for index, bullet in enumerate(bullets[:expected_count], start=1):
        normalized = _normalize_text(bullet)
        word_count = len(normalized.split())
        if word_count < 10:
            errors.append(f"Key Takeaways bullet {index} is too short to carry a specific claim")
            continue
        has_claim = "claim" in normalized or "thesis" in normalized or "argues" in normalized
        has_evidence = any(term in normalized for term in ("evidence", "example", "examples", "because", "proof"))
        has_implication = any(term in normalized for term in ("implication", "means", "so ken", "therefore", "why it matters"))
        if not (has_claim and has_evidence and has_implication):
            errors.append(
                f"Key Takeaways bullet {index} must include claim, evidence/example, and implication"
            )
        if any(stem in normalized for stem in vague_stems) and not has_evidence:
            errors.append(f"Key Takeaways bullet {index} reads like a vague topic label")
    return errors


def validate_summary_contract(
    summary: str | None,
    *,
    word_count: int | None = None,
    duration_seconds: float | None = None,
) -> SummaryQualityResult:
    """Validate the T015 scan-first summary contract.

    Hard errors are reserved for summaries that should not be written during
    live backfill by default. The current brief contract is structured around
    the report sections Ken actually reads: at-a-glance, executive summary, key
    takeaways, detailed brief, concepts, operator notes, and source metadata.
    """
    sections = extract_heading_sections(summary)
    missing = tuple(
        heading for heading in REQUIRED_HEADINGS if _required_section_missing(sections, heading, markdown=summary)
    )
    errors: list[str] = []
    warnings: list[str] = []
    summary_chars = len((summary or "").strip())

    if not (summary or "").strip():
        errors.append("summary is empty")
    if missing:
        errors.append("missing required heading(s): " + ", ".join(missing))

    at_a_glance = _find_any_section(sections, AT_A_GLANCE_HEADINGS, markdown=summary)
    executive_summary = _find_any_section(sections, EXECUTIVE_SUMMARY_HEADINGS, markdown=summary)
    key_takes = _find_any_section(sections, KEY_TAKEAWAY_HEADINGS, markdown=summary)
    detailed_brief = _find_any_section(sections, DETAILED_BRIEF_HEADINGS, markdown=summary)
    operator_notes = _find_any_section(sections, OPERATOR_NOTE_HEADINGS, markdown=summary)

    key_count = count_bullets(key_takes)
    low_content = _is_explicit_low_content(at_a_glance) or _is_explicit_low_content(executive_summary)
    requires_deep = _requires_deep_brief(
        word_count=word_count,
        duration_seconds=duration_seconds,
        is_low_content=low_content,
    )
    minimum_key_takes = (
        LOW_CONTENT_MIN_KEY_TAKES
        if low_content
        else DEEP_MIN_KEY_TAKES
        if requires_deep
        else NORMAL_MIN_KEY_TAKES
    )
    if key_count < minimum_key_takes:
        if low_content:
            warnings.append(
                f"Key takes has {key_count} bullet(s); expected {minimum_key_takes} for short/low-content summaries, accepted because the summary explicitly flags low content"
            )
        else:
            errors.append(
                f"Key takes has {key_count} bullet(s); expected at least {minimum_key_takes} for this transcript length"
            )

    if not low_content and key_takes:
        errors.extend(_vague_key_take_errors(key_takes, expected_count=min(key_count, minimum_key_takes)))

    ken_relevance = operator_notes
    if ken_relevance is None or not ken_relevance.strip():
        errors.append("Operator Notes / Why Ken Should Care section is missing or empty")
    elif not _mentions_ken_focus_or_low_relevance(ken_relevance):
        warnings.append(
            "Operator notes do not mention a Ken focus area (agent systems, AI ops, content/business, investing, GTM, workflow) or plainly say relevance is low"
        )

    verdict = _find_watch_verdict(at_a_glance)
    if verdict is None:
        errors.append("At-a-Glance must contain one of: Skip / Skim / Watch fully")

    executive_summary_chars = len((executive_summary or "").strip())
    detailed_item_count = _count_detailed_items(detailed_brief)
    if requires_deep:
        if summary_chars < DEEP_MIN_SUMMARY_CHARS:
            errors.append(
                f"summary has {summary_chars} chars; expected at least {DEEP_MIN_SUMMARY_CHARS} for long/substantive transcripts"
            )
        if executive_summary_chars < DEEP_MIN_EXECUTIVE_SUMMARY_CHARS:
            errors.append(
                "Executive Summary is too thin for a long/substantive transcript "
                f"({executive_summary_chars} chars)"
            )
        if detailed_item_count < DEEP_MIN_DETAILED_ITEMS:
            errors.append(
                f"Detailed Brief has {detailed_item_count} item(s); expected at least {DEEP_MIN_DETAILED_ITEMS} for long/substantive transcripts"
            )
    return SummaryQualityResult(
        missing_headings=missing,
        key_take_count=key_count,
        minimum_key_takes=minimum_key_takes,
        watch_verdict=verdict,
        ken_relevance=ken_relevance,
        is_low_content=low_content,
        requires_deep_brief=requires_deep,
        executive_summary_chars=executive_summary_chars,
        detailed_brief_item_count=detailed_item_count,
        summary_chars=summary_chars,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


@dataclass(frozen=True)
class ReportDepthResult:
    """Deterministic gate for already-renderable summary reports."""

    requires_deep_brief: bool
    is_low_content: bool
    key_take_count: int
    section_count: int
    summary_chars: int
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.errors

    @property
    def is_too_thin(self) -> bool:
        return bool(self.errors)


def validate_report_depth(
    summary: str | None,
    *,
    word_count: int | None = None,
    duration_seconds: float | None = None,
) -> ReportDepthResult:
    """Block long/substantive videos from shipping as one-paragraph reports.

    This gate is intentionally more permissive than ``validate_summary_contract``
    so older T015 summaries with useful sections can still render, while thin
    long-video teasers are contained until they are regenerated.
    """
    sections = extract_heading_sections(summary)
    summary_chars = len((summary or "").strip())
    low_content = _is_explicit_low_content(summary)
    requires_deep = _requires_deep_brief(
        word_count=word_count,
        duration_seconds=duration_seconds,
        is_low_content=low_content,
    )
    key_takes = _find_any_section(sections, KEY_TAKEAWAY_HEADINGS, markdown=summary)
    key_count = count_bullets(key_takes)

    meaningful_headings = {
        normalize_heading(heading)
        for heading in (
            *EXECUTIVE_SUMMARY_HEADINGS,
            *DETAILED_BRIEF_HEADINGS,
            *CONCEPT_HEADINGS,
            *OPERATOR_NOTE_HEADINGS,
            "Caveats / counterpoints",
            "Action items",
            "Useful details",
        )
    }
    section_count = sum(1 for heading, content in sections.items() if heading in meaningful_headings and content)
    errors: list[str] = []
    warnings: list[str] = []

    if requires_deep:
        if summary_chars < DEEP_MIN_SUMMARY_CHARS:
            errors.append(
                f"summary has {summary_chars} chars; long/substantive reports require at least {DEEP_MIN_SUMMARY_CHARS} chars"
            )
        if key_count < NORMAL_MIN_KEY_TAKES:
            errors.append(
                f"Key Takeaways has {key_count} bullet(s); long/substantive reports require at least {NORMAL_MIN_KEY_TAKES}"
            )
        if section_count < 2:
            errors.append(
                f"report has {section_count} substantive section(s); long/substantive reports require a detailed brief or equivalent supporting sections"
            )

    return ReportDepthResult(
        requires_deep_brief=requires_deep,
        is_low_content=low_content,
        key_take_count=key_count,
        section_count=section_count,
        summary_chars=summary_chars,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def format_summary_quality_messages(result: SummaryQualityResult) -> list[str]:
    """Return compact operator-facing validation lines."""
    if result.passed and not result.warnings:
        return [
            "PASS: structured brief contract valid "
            f"(verdict={result.watch_verdict}, key_takes={result.key_take_count}, "
            f"deep={result.requires_deep_brief}, low_content={result.is_low_content})"
        ]

    lines: list[str] = []
    lines.extend(f"ERROR: {message}" for message in result.errors)
    lines.extend(f"WARNING: {message}" for message in result.warnings)
    return lines


__all__ = [
    "DEEP_BRIEF_DURATION_SECONDS",
    "DEEP_BRIEF_WORD_COUNT",
    "REQUIRED_HEADINGS",
    "ReportDepthResult",
    "SummaryQualityResult",
    "format_summary_quality_messages",
    "validate_report_depth",
    "validate_summary_contract",
]
