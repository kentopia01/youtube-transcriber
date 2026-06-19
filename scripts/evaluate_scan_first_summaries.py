#!/usr/bin/env python3
"""Dry-run evaluation harness for T015 scan-first summaries.

This script reads existing transcript rows, selects a small representative sample,
and writes local markdown artifacts for inspection. It never updates production
summary rows. Live Anthropic generation is opt-in via ``--generate`` and disables
cost-tracker DB writes so the harness remains read-only against Postgres.

Examples:
  python scripts/evaluate_scan_first_summaries.py --list
  python scripts/evaluate_scan_first_summaries.py --youtube-id dQw4w9WgXcQ --metadata-only
  ANTHROPIC_API_KEY=... python scripts/evaluate_scan_first_summaries.py --generate
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.summary_quality import (  # noqa: E402
    format_summary_quality_messages,
    validate_summary_contract,
)

DEFAULT_SAMPLE_CATEGORIES = (
    "long_podcast",
    "short_clip",
    "ai_product_review",
    "low_content",
)

AI_PRODUCT_REVIEW_TERMS = (
    "ai",
    "artificial intelligence",
    "agent",
    "agents",
    "claude",
    "chatgpt",
    "gpt",
    "openai",
    "anthropic",
    "gemini",
    "llm",
    "product",
    "review",
    "demo",
    "hands on",
    "hands-on",
    "benchmark",
)

PODCAST_TERMS = (
    "podcast",
    "interview",
    "conversation",
    "episode",
    "full conversation",
    "debate",
    "fireside",
)

LOW_CONTENT_MARKERS = (
    "[music]",
    "(music)",
    "♪",
    "lyrics",
    "subscribe",
    "thanks for watching",
    "thank you for watching",
    "placeholder",
    "no transcript",
    "transcript unavailable",
)


@dataclass(frozen=True)
class EvalCandidate:
    """Transcript row projected into a pure, testable shape."""

    video_uuid: str
    youtube_video_id: str
    title: str
    channel_name: str | None
    duration_seconds: float | None
    word_count: int | None
    transcript: str
    existing_summary: str | None = None
    summary_model: str | None = None
    published_at: datetime | None = None
    transcription_created_at: datetime | None = None

    @property
    def effective_word_count(self) -> int:
        if self.word_count and self.word_count > 0:
            return self.word_count
        return count_words(self.transcript)


@dataclass(frozen=True)
class SelectedSample:
    category: str
    candidate: EvalCandidate
    reason: str


@dataclass(frozen=True)
class GeneratedSummary:
    summary: str
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def count_words(text: str | None) -> int:
    return len(re.findall(r"[\w']+", text or ""))


def normalize_youtube_id(value: str) -> str:
    """Accept a YouTube ID or common YouTube URL and return the video id."""
    value = (value or "").strip()
    for pattern in (
        r"[?&]v=([^&#?/]+)",
        r"youtu\.be/([^&#?/]+)",
        r"/shorts/([^&#?/]+)",
        r"/embed/([^&#?/]+)",
    ):
        match = re.search(pattern, value)
        if match:
            return match.group(1)
    return value


def format_duration(seconds: float | None) -> str:
    if not seconds:
        return "unknown"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def markdown_excerpt(text: str | None, *, max_chars: int = 900) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return "_No existing summary._"
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def _slugify(value: str, *, fallback: str = "video") -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return (slug[:80] or fallback).strip("-") or fallback


def _haystack(candidate: EvalCandidate) -> str:
    return " ".join(
        part
        for part in [candidate.title, candidate.channel_name or "", candidate.existing_summary or ""]
        if part
    ).lower()


def _contains_term(haystack: str, term: str) -> bool:
    if re.fullmatch(r"[a-z0-9]+", term):
        return re.search(rf"\b{re.escape(term)}\b", haystack) is not None
    return term in haystack


def is_low_content_candidate(candidate: EvalCandidate) -> bool:
    wc = candidate.effective_word_count
    text = (candidate.transcript or "").strip().lower()
    if wc <= 80:
        return True
    if wc <= 250 and any(marker in text for marker in LOW_CONTENT_MARKERS):
        return True

    lines = [re.sub(r"\s+", " ", line.strip().lower()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if len(lines) >= 4:
        most_common = max(lines.count(line) for line in set(lines))
        if most_common / len(lines) >= 0.6:
            return True

    words = re.findall(r"[a-z0-9']+", text)
    if 80 < len(words) <= 300:
        unique_ratio = len(set(words)) / max(len(words), 1)
        if unique_ratio < 0.18:
            return True
    return False


def _long_podcast_score(candidate: EvalCandidate) -> float:
    if is_low_content_candidate(candidate):
        return 0
    duration = candidate.duration_seconds or 0
    wc = candidate.effective_word_count
    if duration < 1800 and wc < 4500:
        return 0
    score = duration / 60 + wc / 100
    haystack = _haystack(candidate)
    if any(_contains_term(haystack, term) for term in PODCAST_TERMS):
        score += 500
    return score


def _short_clip_score(candidate: EvalCandidate) -> float:
    if is_low_content_candidate(candidate):
        return 0
    duration = candidate.duration_seconds or 0
    wc = candidate.effective_word_count
    if duration > 600 and wc > 1500:
        return 0
    if wc < 100:
        return 0
    # Prefer useful clips around 3-7 minutes over tiny fragments.
    target_seconds = 300
    duration_penalty = abs((duration or target_seconds) - target_seconds) / 60
    return 1000 - duration_penalty - (wc / 5000)


def _ai_product_review_score(candidate: EvalCandidate) -> float:
    if is_low_content_candidate(candidate):
        return 0
    haystack = _haystack(candidate)
    score = 0.0
    for term in AI_PRODUCT_REVIEW_TERMS:
        if _contains_term(haystack, term):
            score += 100
    if any(_contains_term(haystack, term) for term in ("review", "demo", "hands")):
        score += 150
    if any(_contains_term(haystack, term) for term in ("ai", "claude", "gpt", "agent")):
        score += 150
    if score == 0:
        return 0
    return score + min(candidate.effective_word_count / 100, 50)


def _low_content_score(candidate: EvalCandidate) -> float:
    if not is_low_content_candidate(candidate):
        return 0
    wc = candidate.effective_word_count
    marker_bonus = 100 if any(marker in (candidate.transcript or "").lower() for marker in LOW_CONTENT_MARKERS) else 0
    return 1000 + marker_bonus - wc


def _select_best(
    candidates: Iterable[EvalCandidate],
    *,
    score_fn,
    seen: set[str],
) -> EvalCandidate | None:
    scored = [
        (score_fn(candidate), candidate)
        for candidate in candidates
        if candidate.youtube_video_id not in seen
    ]
    scored = [(score, candidate) for score, candidate in scored if score > 0]
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1].effective_word_count), reverse=True)
    return scored[0][1]


def select_representative_samples(
    candidates: Sequence[EvalCandidate],
    *,
    explicit_youtube_ids: Sequence[str] | None = None,
    include_defaults: bool = False,
    max_samples: int = 4,
) -> list[SelectedSample]:
    """Select explicit IDs and/or the default representative T015 sample set."""
    by_youtube_id = {candidate.youtube_video_id: candidate for candidate in candidates}
    selected: list[SelectedSample] = []
    seen: set[str] = set()

    explicit_ids = [normalize_youtube_id(value) for value in (explicit_youtube_ids or [])]
    for youtube_id in explicit_ids:
        candidate = by_youtube_id.get(youtube_id)
        if not candidate or youtube_id in seen:
            continue
        selected.append(SelectedSample("explicit", candidate, "requested by --youtube-id"))
        seen.add(youtube_id)

    should_select_defaults = include_defaults or not explicit_ids
    if should_select_defaults:
        category_specs = [
            ("long_podcast", _long_podcast_score, "long-form transcript/podcast-style sample"),
            ("short_clip", _short_clip_score, "short but substantive clip"),
            ("ai_product_review", _ai_product_review_score, "AI/product/review-oriented sample"),
            ("low_content", _low_content_score, "low-content or placeholder transcript sample"),
        ]
        for category, score_fn, reason in category_specs:
            if len(selected) >= max_samples:
                break
            candidate = _select_best(candidates, score_fn=score_fn, seen=seen)
            if candidate:
                selected.append(SelectedSample(category, candidate, reason))
                seen.add(candidate.youtube_video_id)

    if should_select_defaults and len(selected) < max_samples:
        fallback_candidates = sorted(
            (candidate for candidate in candidates if candidate.youtube_video_id not in seen),
            key=lambda c: (c.effective_word_count, c.duration_seconds or 0),
            reverse=True,
        )
        for candidate in fallback_candidates:
            if len(selected) >= max_samples:
                break
            selected.append(
                SelectedSample(
                    "fallback",
                    candidate,
                    "fallback sample because not all target categories were available",
                )
            )
            seen.add(candidate.youtube_video_id)

    return selected[:max_samples]


def render_eval_markdown(
    sample: SelectedSample,
    *,
    generated: GeneratedSummary | None,
    prompt_model: str | None,
    generated_at: datetime | None = None,
    transcript_preview_chars: int = 1200,
) -> str:
    candidate = sample.candidate
    generated_at = generated_at or datetime.now(UTC)
    generated_summary = (
        generated.summary
        if generated
        else "_Not generated. Run this harness with `--generate` and `ANTHROPIC_API_KEY` to call Anthropic. No production summary rows will be updated._"
    )
    if generated:
        quality_lines = format_summary_quality_messages(
            validate_summary_contract(
                generated.summary,
                word_count=candidate.effective_word_count,
                duration_seconds=candidate.duration_seconds,
            )
        )
    else:
        quality_lines = ["Not run because no summary was generated."]
    transcript_preview = markdown_excerpt(candidate.transcript, max_chars=transcript_preview_chars)

    lines = [
        f"# Scan-first summary eval: {candidate.title}",
        "",
        "## Metadata",
        f"- Category: `{sample.category}`",
        f"- Selection reason: {sample.reason}",
        f"- YouTube ID: `{candidate.youtube_video_id}`",
        f"- Video UUID: `{candidate.video_uuid}`",
        f"- Channel: {candidate.channel_name or 'unknown'}",
        f"- Duration: {format_duration(candidate.duration_seconds)}",
        f"- Word count: {candidate.effective_word_count}",
        f"- Existing summary model: {candidate.summary_model or 'unknown'}",
        f"- Prompt model: {generated.model if generated and generated.model else prompt_model or 'not generated'}",
        f"- Generated at: {generated_at.astimezone(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "- Production summary DB writes: none",
    ]
    if generated and (generated.prompt_tokens is not None or generated.completion_tokens is not None):
        lines.extend(
            [
                f"- Prompt tokens: {generated.prompt_tokens if generated.prompt_tokens is not None else 'unknown'}",
                f"- Completion tokens: {generated.completion_tokens if generated.completion_tokens is not None else 'unknown'}",
            ]
        )
    lines.extend(
        [
            "",
            "## Existing summary excerpt",
            markdown_excerpt(candidate.existing_summary),
            "",
            "## Generated scan-first summary",
            generated_summary.strip(),
            "",
            "## Contract validation",
            *(f"- {line}" for line in quality_lines),
            "",
            "## Transcript preview",
            transcript_preview,
            "",
        ]
    )
    return "\n".join(lines)


def write_eval_outputs(
    samples: Sequence[SelectedSample],
    *,
    generated_by_youtube_id: dict[str, GeneratedSummary],
    output_dir: Path,
    prompt_model: str | None,
    generated_at: datetime | None = None,
    transcript_preview_chars: int = 1200,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = generated_at or datetime.now(UTC)
    written: list[Path] = []

    index_lines = [
        "# T015 scan-first summary evaluation",
        "",
        f"Generated at: {generated_at.astimezone(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "This is a local dry-run artifact. It does not update production `summaries` rows.",
        "",
        "| # | Category | YouTube ID | Title | Channel | Words | Output |",
        "|---:|---|---|---|---|---:|---|",
    ]

    for index, sample in enumerate(samples, start=1):
        candidate = sample.candidate
        filename = (
            f"{index:02d}-{sample.category}-{candidate.youtube_video_id}-"
            f"{_slugify(candidate.title)}.md"
        )
        path = output_dir / filename
        markdown = render_eval_markdown(
            sample,
            generated=generated_by_youtube_id.get(candidate.youtube_video_id),
            prompt_model=prompt_model,
            generated_at=generated_at,
            transcript_preview_chars=transcript_preview_chars,
        )
        path.write_text(markdown, encoding="utf-8")
        written.append(path)
        index_lines.append(
            "| {index} | `{category}` | `{youtube_id}` | {title} | {channel} | {words} | [{filename}]({filename}) |".format(
                index=index,
                category=sample.category,
                youtube_id=candidate.youtube_video_id,
                title=candidate.title.replace("|", "\\|"),
                channel=(candidate.channel_name or "unknown").replace("|", "\\|"),
                words=candidate.effective_word_count,
                filename=filename,
            )
        )

    index_path = output_dir / "index.md"
    index_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    return [index_path, *written]


def _parse_env_file_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return None


def _syncify_db_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")


def resolve_db_url_sync(explicit: str | None = None) -> str:
    if explicit:
        return _syncify_db_url(explicit)
    if os.environ.get("DATABASE_URL_SYNC"):
        return _syncify_db_url(os.environ["DATABASE_URL_SYNC"])
    if os.environ.get("DATABASE_URL_NATIVE"):
        return _syncify_db_url(os.environ["DATABASE_URL_NATIVE"])

    native_env = PROJECT_ROOT / ".env.native"
    for key in ("DATABASE_URL_SYNC", "DATABASE_URL_NATIVE", "DATABASE_URL"):
        value = _parse_env_file_value(native_env, key)
        if value:
            return _syncify_db_url(value)

    from app.config import settings

    return _syncify_db_url(settings.database_url_sync)


def load_candidates_from_db(
    db,
    *,
    youtube_ids: Sequence[str] | None = None,
    limit: int = 250,
) -> list[EvalCandidate]:
    from app.models.channel import Channel
    from app.models.summary import Summary
    from app.models.transcription import Transcription
    from app.models.video import Video

    normalized_ids = [normalize_youtube_id(value) for value in (youtube_ids or [])]
    query = (
        db.query(Video, Transcription, Summary, Channel)
        .join(Transcription, Transcription.video_id == Video.id)
        .outerjoin(Summary, Summary.video_id == Video.id)
        .outerjoin(Channel, Channel.id == Video.channel_id)
        .filter(Transcription.full_text.isnot(None))
        .filter(Transcription.full_text != "")
    )
    if normalized_ids:
        query = query.filter(Video.youtube_video_id.in_(normalized_ids))
    else:
        query = query.order_by(Transcription.created_at.desc()).limit(limit)

    rows = query.all()
    return [
        EvalCandidate(
            video_uuid=str(video.id),
            youtube_video_id=video.youtube_video_id,
            title=video.title,
            channel_name=channel.name if channel else None,
            duration_seconds=video.duration_seconds,
            word_count=transcription.word_count,
            transcript=transcription.full_text,
            existing_summary=summary.content if summary else None,
            summary_model=summary.model if summary else None,
            published_at=video.published_at,
            transcription_created_at=transcription.created_at,
        )
        for video, transcription, summary, channel in rows
    ]


def print_sample_list(samples: Sequence[SelectedSample]) -> None:
    if not samples:
        print("No transcript candidates selected.")
        return
    for sample in samples:
        candidate = sample.candidate
        print(
            f"{sample.category:17} {candidate.youtube_video_id:15} "
            f"words={candidate.effective_word_count:<7} "
            f"duration={format_duration(candidate.duration_seconds):<9} "
            f"channel={candidate.channel_name or '-'} | {candidate.title}"
        )


def generate_scan_first_summary(
    candidate: EvalCandidate,
    *,
    api_key: str,
    model: str,
) -> GeneratedSummary:
    from app.services.summarization import summarize_text

    result = summarize_text(
        candidate.transcript,
        video_title=candidate.title,
        api_key=api_key,
        model=model,
        record_usage_enabled=False,
        video_duration_seconds=candidate.duration_seconds,
    )
    return GeneratedSummary(
        summary=result["summary"],
        model=result.get("model"),
        prompt_tokens=result.get("prompt_tokens"),
        completion_tokens=result.get("completion_tokens"),
    )


def default_output_dir() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return PROJECT_ROOT / "reports" / "eval" / f"scan-first-{stamp}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate the T015 scan-first summary prompt against existing transcripts without updating summaries."
    )
    parser.add_argument(
        "--youtube-id",
        action="append",
        default=[],
        help="Specific YouTube video ID or URL to include. Repeat for multiple videos.",
    )
    parser.add_argument(
        "--include-defaults",
        action="store_true",
        help="When --youtube-id is supplied, also add the representative default sample set.",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=4,
        help="Maximum selected samples to inspect (default: 4).",
    )
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=250,
        help="How many recent transcript rows to scan for default representative samples (default: 250).",
    )
    parser.add_argument("--db-url", help="Override sync PostgreSQL URL for reads.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for markdown eval outputs (default: reports/eval/scan-first-<timestamp>).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Cheap mode: print selected candidates only; no Anthropic call and no markdown files.",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Write inspectable markdown shells without calling Anthropic. This is the default unless --generate is used.",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Call Anthropic and write generated scan-first summaries to local markdown files. Still no DB writes.",
    )
    parser.add_argument("--api-key", default=os.environ.get("ANTHROPIC_API_KEY", ""), help="Anthropic API key for --generate.")
    parser.add_argument("--model", default=None, help="Anthropic model override for --generate.")
    parser.add_argument(
        "--transcript-preview-chars",
        type=int,
        default=1200,
        help="Transcript preview length in markdown outputs (default: 1200 chars).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list and args.generate:
        parser.error("--list and --generate are mutually exclusive")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    explicit_ids = [normalize_youtube_id(value) for value in args.youtube_id]
    need_defaults = args.include_defaults or not explicit_ids

    db_url = resolve_db_url_sync(args.db_url)
    engine = create_engine(db_url)
    with Session(engine) as db:
        candidates: list[EvalCandidate] = []
        if explicit_ids:
            candidates.extend(load_candidates_from_db(db, youtube_ids=explicit_ids, limit=args.candidate_limit))
        if need_defaults:
            existing_ids = {candidate.youtube_video_id for candidate in candidates}
            default_candidates = load_candidates_from_db(db, limit=args.candidate_limit)
            candidates.extend(
                candidate for candidate in default_candidates if candidate.youtube_video_id not in existing_ids
            )

    samples = select_representative_samples(
        candidates,
        explicit_youtube_ids=explicit_ids,
        include_defaults=args.include_defaults,
        max_samples=max(args.max_samples, 1),
    )

    missing = sorted(set(explicit_ids) - {sample.candidate.youtube_video_id for sample in samples})
    if missing:
        print("Missing requested YouTube IDs with transcripts: " + ", ".join(missing), file=sys.stderr)

    if args.list:
        print_sample_list(samples)
        return 0 if samples else 1

    generated: dict[str, GeneratedSummary] = {}
    model = args.model
    if args.generate:
        if not args.api_key:
            parser.error("--generate requires ANTHROPIC_API_KEY or --api-key")
        if not model:
            from app.config import settings

            model = settings.summary_model
        for sample in samples:
            candidate = sample.candidate
            print(f"Generating {sample.category}: {candidate.youtube_video_id} — {candidate.title}")
            generated_summary = generate_scan_first_summary(
                candidate,
                api_key=args.api_key,
                model=model,
            )
            generated[candidate.youtube_video_id] = generated_summary
            quality = validate_summary_contract(
                generated_summary.summary,
                word_count=candidate.effective_word_count,
                duration_seconds=candidate.duration_seconds,
            )
            for line in format_summary_quality_messages(quality):
                if not line.startswith("PASS:"):
                    print(f"  {line}")
    else:
        # Explicitly document default behavior in stdout; --metadata-only is an alias for this mode.
        print("Metadata-only dry-run: no Anthropic calls and no DB writes. Use --generate for live summaries.")

    output_dir = args.output_dir or default_output_dir()
    written = write_eval_outputs(
        samples,
        generated_by_youtube_id=generated,
        output_dir=output_dir,
        prompt_model=model,
        transcript_preview_chars=args.transcript_preview_chars,
    )
    print_sample_list(samples)
    print(f"Wrote {len(written)} markdown file(s) under {output_dir}")
    return 0 if samples else 1


if __name__ == "__main__":
    raise SystemExit(main())
