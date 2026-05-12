"""Deterministic guardrails for T015 scan-first summaries.

This module is intentionally pure: it checks the markdown contract produced by
summarization/backfill flows and returns warnings/errors for operators. It does
not call an LLM and does not persist anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.summary_markdown import count_bullets, extract_heading_sections, find_section

REQUIRED_HEADINGS: tuple[str, ...] = (
    "30-second take",
    "Key takes",
    "Useful details",
    "Caveats / counterpoints",
    "Ken relevance",
    "Watch verdict",
)

WATCH_VERDICTS: tuple[str, ...] = ("Skip", "Skim", "Watch fully")
NORMAL_MIN_KEY_TAKES = 4
LOW_CONTENT_MIN_KEY_TAKES = 2

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
    verdict_patterns = (
        ("Watch fully", r"\bwatch\s+fully\b"),
        ("Skim", r"\bskim\b"),
        ("Skip", r"\bskip\b"),
    )
    for verdict, pattern in verdict_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return verdict
    return None


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


def validate_summary_contract(summary: str | None, *, word_count: int | None = None) -> SummaryQualityResult:
    """Validate the T015 scan-first summary contract.

    Hard errors are reserved for summaries that should not be written during
    live backfill by default. Key-take count is a hard error for substantive
    non-low-content transcripts; explicitly low-content transcripts may pass
    with fewer key takes while emitting an operator warning.
    """
    sections = extract_heading_sections(summary)
    missing = tuple(heading for heading in REQUIRED_HEADINGS if find_section(sections, heading) is None)
    errors: list[str] = []
    warnings: list[str] = []

    if not (summary or "").strip():
        errors.append("summary is empty")
    if missing:
        errors.append("missing required heading(s): " + ", ".join(missing))

    key_takes = find_section(sections, "Key takes")
    key_count = count_bullets(key_takes)
    low_content = _is_explicit_low_content(find_section(sections, "30-second take"))
    minimum_key_takes = LOW_CONTENT_MIN_KEY_TAKES if low_content else NORMAL_MIN_KEY_TAKES
    if key_count < minimum_key_takes:
        if low_content:
            warnings.append(
                f"Key takes has {key_count} bullet(s); expected {minimum_key_takes} for short/low-content summaries, accepted because the summary explicitly flags low content"
            )
        else:
            errors.append(
                f"Key takes has {key_count} bullet(s); expected at least {minimum_key_takes} for this transcript length"
            )

    ken_relevance = find_section(sections, "Ken relevance")
    if ken_relevance is None or not ken_relevance.strip():
        errors.append("Ken relevance section is missing or empty")
    elif not _mentions_ken_focus_or_low_relevance(ken_relevance):
        warnings.append(
            "Ken relevance does not mention a Ken focus area (agent systems, AI ops, content/business, investing, GTM, workflow) or plainly say relevance is low"
        )

    verdict = _find_watch_verdict(find_section(sections, "Watch verdict"))
    if verdict is None:
        errors.append("Watch verdict must contain one of: Skip / Skim / Watch fully")

    return SummaryQualityResult(
        missing_headings=missing,
        key_take_count=key_count,
        minimum_key_takes=minimum_key_takes,
        watch_verdict=verdict,
        ken_relevance=ken_relevance,
        is_low_content=low_content,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def format_summary_quality_messages(result: SummaryQualityResult) -> list[str]:
    """Return compact operator-facing validation lines."""
    if result.passed and not result.warnings:
        return [
            "PASS: scan-first summary contract valid "
            f"(verdict={result.watch_verdict}, key_takes={result.key_take_count}, low_content={result.is_low_content})"
        ]

    lines: list[str] = []
    lines.extend(f"ERROR: {message}" for message in result.errors)
    lines.extend(f"WARNING: {message}" for message in result.warnings)
    return lines


__all__ = [
    "REQUIRED_HEADINGS",
    "SummaryQualityResult",
    "format_summary_quality_messages",
    "validate_summary_contract",
]
