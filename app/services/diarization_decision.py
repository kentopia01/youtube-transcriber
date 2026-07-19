"""Cheap heuristics for deciding whether speaker labels are worth adding."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Iterable


DECISION_SKIP = "skip"
DECISION_DEFER = "defer"
DECISION_REVIEW = "review"

PROFILE_LIKELY_SOLO = "likely_solo"
PROFILE_LIKELY_MULTI = "likely_multi_speaker"
PROFILE_UNCERTAIN = "uncertain"

VALUE_LOW = "low"
VALUE_MEDIUM = "medium"
VALUE_HIGH = "high"

DETECTOR_NAME = "heuristic_v1"
SCHEMA_VERSION = 1

_MULTI_FORMAT_TERMS = {
    "podcast",
    "interview",
    "panel",
    "debate",
    "roundtable",
    "fireside",
    "conversation",
    "ama",
    "ask me anything",
    "q&a",
    "live q&a",
}

_MULTI_TITLE_REGEXES = [
    re.compile(r"\bwith\s+[\w.-]+", re.IGNORECASE),
    re.compile(r"\bfeat(?:\.|uring)?\s+[\w.-]+", re.IGNORECASE),
    re.compile(r"\bft\.\s*[\w.-]+", re.IGNORECASE),
    re.compile(r"\bvs\.?\s+[\w.-]+", re.IGNORECASE),
]

_MULTI_TRANSCRIPT_PHRASES = {
    "thanks for having me",
    "thank you for having me",
    "my guest",
    "our guest",
    "joined by",
    "welcome to the show",
    "welcome back to the show",
    "let me ask you",
    "what do you think",
    "how do you think about",
    "tell us about",
    "question from",
    "audience question",
}

_SOLO_FORMAT_TERMS = {
    "tutorial",
    "lecture",
    "keynote",
    "course",
    "lesson",
    "walkthrough",
    "demo",
    "coding",
    "build",
    "presentation",
    "explained",
    "from scratch",
}

_SOLO_TRANSCRIPT_PHRASES = {
    "in this video",
    "today i want to",
    "today i'm going to",
    "i'm going to show",
    "i want to show",
    "let's build",
    "we're going to build",
    "let's walk through",
    "i'll show you",
    "in this lecture",
}


@dataclass(frozen=True)
class DiarizationDecision:
    schema_version: int
    detector: str
    decision: str
    speaker_profile: str
    speaker_labels_value: str
    confidence: float
    reasons: list[str]
    signals: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _normalize(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _contains_term(text: str, term: str) -> bool:
    if len(term) <= 3 or not term.replace("&", "").replace(" ", "").isalnum():
        return term in text
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _matched_terms(text: str, terms: Iterable[str]) -> list[str]:
    return sorted(term for term in terms if _contains_term(text, term))


def _sample_segment_text(segment_texts: Iterable[str] | None) -> str:
    segments = [text.strip() for text in segment_texts or [] if text and text.strip()]
    if not segments:
        return ""

    window = 5
    if len(segments) <= window * 3:
        selected = segments
    else:
        midpoint = len(segments) // 2
        selected = (
            segments[:window]
            + segments[max(0, midpoint - 2): midpoint + 3]
            + segments[-window:]
        )
    return " ".join(selected)


def _bounded_text(*parts: str | None, limit: int = 12000) -> str:
    text = _normalize(" ".join(part for part in parts if part))
    return text[:limit]


def decide_diarization_usefulness(
    *,
    title: str | None,
    description: str | None = None,
    channel_name: str | None = None,
    transcript_text: str | None = None,
    segment_texts: Iterable[str] | None = None,
) -> DiarizationDecision:
    """Return a bounded, deterministic decision about speaker-label usefulness.

    This is intentionally cheaper than diarization. It only inspects metadata and
    transcript snippets, and it stores matched signals instead of transcript text.
    """
    title_text = _normalize(title)
    channel_text = _normalize(channel_name)
    description_text = _bounded_text(description, limit=2500)
    sampled_segments = _sample_segment_text(segment_texts)
    transcript_sample = _bounded_text(sampled_segments or transcript_text, limit=12000)
    metadata_text = _bounded_text(title_text, channel_text, description_text, limit=5000)

    title_multi_terms = _matched_terms(title_text, _MULTI_FORMAT_TERMS)
    channel_multi_terms = _matched_terms(channel_text, {"podcast", "show", "interview"})
    description_multi_terms = _matched_terms(description_text, {"interview", "panel", "podcast", "guest"})
    transcript_multi_terms = _matched_terms(transcript_sample, _MULTI_TRANSCRIPT_PHRASES)
    title_multi_regexes = [
        pattern.pattern
        for pattern in _MULTI_TITLE_REGEXES
        if pattern.search(title or "")
    ]

    title_solo_terms = _matched_terms(title_text, _SOLO_FORMAT_TERMS)
    description_solo_terms = _matched_terms(description_text, {"tutorial", "lecture", "demo", "course"})
    transcript_solo_terms = _matched_terms(transcript_sample, _SOLO_TRANSCRIPT_PHRASES)

    question_count = transcript_sample.count("?")

    multi_score = (
        len(title_multi_terms) * 2
        + len(channel_multi_terms)
        + len(description_multi_terms)
        + len(title_multi_regexes)
        + len(transcript_multi_terms) * 2
        + (1 if question_count >= 5 else 0)
    )
    solo_score = (
        len(title_solo_terms) * 2
        + len(description_solo_terms)
        + len(transcript_solo_terms)
    )

    reasons: list[str] = []
    if title_multi_terms or title_multi_regexes:
        reasons.append("title suggests a multi-speaker format")
    if channel_multi_terms:
        reasons.append("channel name suggests recurring conversation content")
    if description_multi_terms:
        reasons.append("description mentions interview/panel/guest cues")
    if transcript_multi_terms:
        reasons.append("transcript sample contains conversation cues")
    if question_count >= 5:
        reasons.append("transcript sample has repeated questions")
    if title_solo_terms:
        reasons.append("title suggests solo instructional content")
    if transcript_solo_terms:
        reasons.append("transcript sample suggests monologue/tutorial delivery")

    if multi_score >= 3 and multi_score >= solo_score + 1:
        decision = DECISION_DEFER
        profile = PROFILE_LIKELY_MULTI
        value = VALUE_HIGH
        confidence = min(0.92, 0.58 + (multi_score * 0.06))
    elif solo_score >= 2 and multi_score == 0:
        decision = DECISION_SKIP
        profile = PROFILE_LIKELY_SOLO
        value = VALUE_LOW
        confidence = min(0.88, 0.62 + (solo_score * 0.06))
    elif solo_score >= 4 and multi_score <= 1:
        decision = DECISION_SKIP
        profile = PROFILE_LIKELY_SOLO
        value = VALUE_LOW
        confidence = min(0.82, 0.56 + (solo_score * 0.05))
    elif multi_score >= 2:
        decision = DECISION_DEFER
        profile = PROFILE_LIKELY_MULTI
        value = VALUE_MEDIUM
        confidence = min(0.78, 0.52 + (multi_score * 0.06))
    else:
        decision = DECISION_REVIEW
        profile = PROFILE_UNCERTAIN
        value = VALUE_MEDIUM
        confidence = 0.45
        if not reasons:
            reasons.append("no strong solo or multi-speaker signals found")

    signals = {
        "multi_score": multi_score,
        "solo_score": solo_score,
        "question_count": question_count,
        "matched": {
            "title_multi_terms": title_multi_terms,
            "title_multi_regexes": title_multi_regexes,
            "channel_multi_terms": channel_multi_terms,
            "description_multi_terms": description_multi_terms,
            "transcript_multi_terms": transcript_multi_terms,
            "title_solo_terms": title_solo_terms,
            "description_solo_terms": description_solo_terms,
            "transcript_solo_terms": transcript_solo_terms,
        },
        "sampled_transcript": bool(transcript_sample),
        "metadata_available": bool(metadata_text),
    }

    return DiarizationDecision(
        schema_version=SCHEMA_VERSION,
        detector=DETECTOR_NAME,
        decision=decision,
        speaker_profile=profile,
        speaker_labels_value=value,
        confidence=round(confidence, 2),
        reasons=reasons,
        signals=signals,
    )
