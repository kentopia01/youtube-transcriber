#!/usr/bin/env python3
"""Controlled T015 scan-first summary/report backfill.

Default mode is a read-only dry-run: it selects completed videos with
transcriptions and prints the exact plan. It does not call Anthropic and does
not write summary/report rows unless all live-mode safety flags are present.

Examples:
  python scripts/backfill_scan_first_summaries.py --limit 5
  python scripts/backfill_scan_first_summaries.py --youtube-id abc123,def456
  python scripts/backfill_scan_first_summaries.py --channel "Latent Space" --since 2026-05-01
  ANTHROPIC_API_KEY=... python scripts/backfill_scan_first_summaries.py --limit 2 --apply --generate --confirm-apply

Malformed generated summaries are blocked before DB writes unless the operator
uses the documented override flag: --allow-malformed.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluate_scan_first_summaries import (  # noqa: E402
    count_words,
    normalize_youtube_id,
    resolve_db_url_sync,
)
from app.services.summary_quality import (  # noqa: E402
    SummaryQualityResult,
    format_summary_quality_messages,
    validate_summary_contract,
)


@dataclass(frozen=True)
class BackfillCandidate:
    """Completed transcription projected into a pure, testable shape."""

    video_uuid: str
    youtube_video_id: str
    title: str
    channel_name: str | None
    status: str
    transcript: str
    channel_youtube_id: str | None = None
    duration_seconds: float | None = None
    word_count: int | None = None
    existing_summary: str | None = None
    summary_model: str | None = None
    summary_created_at: datetime | None = None
    transcription_created_at: datetime | None = None
    published_at: datetime | None = None

    @property
    def effective_word_count(self) -> int:
        if self.word_count and self.word_count > 0:
            return self.word_count
        return count_words(self.transcript)

    @property
    def existing_summary_chars(self) -> int:
        return len((self.existing_summary or "").strip())


@dataclass(frozen=True)
class BackfillPlanItem:
    candidate: BackfillCandidate
    intended_action: str


@dataclass(frozen=True)
class GeneratedBackfillSummary:
    summary: str
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class AppliedBackfillResult:
    youtube_video_id: str
    title: str
    summary_chars: int
    prompt_tokens: int | None
    completion_tokens: int | None
    report_path: str | None
    validation_warnings: tuple[str, ...] = ()
    validation_errors: tuple[str, ...] = ()


class SummaryValidationError(RuntimeError):
    """Raised when a live backfill summary fails deterministic safety checks."""

    def __init__(self, youtube_video_id: str, result: SummaryQualityResult):
        self.youtube_video_id = youtube_video_id
        self.result = result
        super().__init__(
            f"generated summary for {youtube_video_id} failed scan-first validation; "
            "use --allow-malformed only for a documented operator override"
        )


def parse_youtube_id_args(values: Sequence[str] | None) -> list[str]:
    """Parse repeatable and comma-separated YouTube IDs/URLs."""
    parsed: list[str] = []
    seen: set[str] = set()
    for raw_value in values or []:
        for part in str(raw_value).split(","):
            youtube_id = normalize_youtube_id(part.strip())
            if youtube_id and youtube_id not in seen:
                parsed.append(youtube_id)
                seen.add(youtube_id)
    return parsed


def parse_since_datetime(value: str | None) -> datetime | None:
    """Parse YYYY-MM-DD or ISO datetime into an aware UTC datetime."""
    if not value:
        return None
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("--since must be YYYY-MM-DD or an ISO datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _matches_channel(candidate: BackfillCandidate, channel_filter: str | None) -> bool:
    if not channel_filter:
        return True
    needle = channel_filter.strip().lower()
    if not needle:
        return True
    return (
        needle in (candidate.channel_name or "").lower()
        or needle == (candidate.channel_youtube_id or "").lower()
    )


def filter_candidates(
    candidates: Sequence[BackfillCandidate],
    *,
    youtube_ids: Sequence[str] | None = None,
    channel: str | None = None,
    since: datetime | None = None,
    completed_only: bool = True,
    limit: int | None = None,
) -> list[BackfillCandidate]:
    """Apply the same safety filters used by the DB loader to in-memory rows."""
    normalized_ids = set(parse_youtube_id_args(youtube_ids))
    since_utc = _aware_utc(since)
    filtered: list[BackfillCandidate] = []

    for candidate in candidates:
        if completed_only and candidate.status != "completed":
            continue
        if normalized_ids and candidate.youtube_video_id not in normalized_ids:
            continue
        if not _matches_channel(candidate, channel):
            continue
        if since_utc:
            transcribed_at = _aware_utc(candidate.transcription_created_at)
            if transcribed_at is None or transcribed_at < since_utc:
                continue
        filtered.append(candidate)

    if limit is not None:
        filtered = filtered[:limit]
    return filtered


def build_backfill_plan(candidates: Sequence[BackfillCandidate]) -> list[BackfillPlanItem]:
    plan: list[BackfillPlanItem] = []
    for candidate in candidates:
        if candidate.existing_summary_chars:
            action = "replace summary; regenerate summary_report artifact"
        else:
            action = "create summary; generate summary_report artifact"
        plan.append(BackfillPlanItem(candidate=candidate, intended_action=action))
    return plan


def summary_age_label(candidate: BackfillCandidate, *, now: datetime | None = None) -> str:
    if not candidate.existing_summary_chars:
        return "none"
    created_at = _aware_utc(candidate.summary_created_at)
    if created_at is None:
        return "unknown age"
    now_utc = _aware_utc(now) or datetime.now(UTC)
    delta = now_utc - created_at
    if delta.total_seconds() < 0:
        delta = timedelta(0)
    days = delta.days
    if days >= 1:
        return f"{days}d old"
    hours = int(delta.total_seconds() // 3600)
    if hours >= 1:
        return f"{hours}h old"
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes}m old"


def existing_summary_label(candidate: BackfillCandidate, *, now: datetime | None = None) -> str:
    if not candidate.existing_summary_chars:
        return "none"
    model = candidate.summary_model or "unknown model"
    return f"{summary_age_label(candidate, now=now)}, {candidate.existing_summary_chars} chars, {model}"


def validate_requested_mode(
    *,
    apply: bool,
    generate: bool,
    confirm_apply: bool,
    limit: int | None,
) -> list[str]:
    """Return mode/safety errors; empty means the requested mode is allowed."""
    errors: list[str] = []
    if limit is not None and limit <= 0:
        errors.append("--limit must be greater than 0")
    if generate and not apply:
        errors.append("--generate is only allowed with --apply; use the eval harness for local generated samples")
    if apply and not generate:
        errors.append("--apply requires --generate so DB writes cannot happen without an explicit Anthropic opt-in")
    if apply and generate and not confirm_apply:
        errors.append("live backfill requires --confirm-apply in addition to --apply --generate")
    return errors


def _filters_label(
    *,
    limit: int | None,
    youtube_ids: Sequence[str],
    channel: str | None,
    since: datetime | None,
    completed_only: bool,
) -> str:
    since_text = since.astimezone(UTC).isoformat() if since else "none"
    ids_text = ",".join(youtube_ids) if youtube_ids else "none"
    return (
        f"completed_only={completed_only} limit={limit if limit is not None else 'none'} "
        f"youtube_ids={ids_text} channel={channel or 'none'} since={since_text}"
    )


def print_backfill_plan(
    plan: Sequence[BackfillPlanItem],
    *,
    dry_run: bool,
    filters_label: str,
    now: datetime | None = None,
) -> None:
    if dry_run:
        print("Mode: DRY RUN — no Anthropic calls and no DB writes.")
        print("Re-run with --apply --generate --confirm-apply to update a limited batch.")
    else:
        print("Mode: LIVE APPLY — Anthropic calls and DB writes are enabled for this limited batch.")
    print(
        "Validation: generated briefs are checked for required report sections, key takeaway depth, "
        "operator notes, and Watch verdict before writes; malformed outputs are blocked unless --allow-malformed is set."
    )
    print(f"Filters: {filters_label}")
    print(f"Selected videos: {len(plan)}")
    if not plan:
        print("No matching completed transcriptions found.")
        return

    for index, item in enumerate(plan, start=1):
        candidate = item.candidate
        print(f"\n[{index}] {candidate.youtube_video_id}")
        print(f"    title: {candidate.title}")
        print(f"    channel: {candidate.channel_name or 'unknown'}")
        print(f"    status: {candidate.status}")
        if candidate.duration_seconds is not None:
            print(f"    duration_seconds: {int(candidate.duration_seconds)}")
        print(f"    word_count: {candidate.effective_word_count}")
        print(f"    existing_summary: {existing_summary_label(candidate, now=now)}")
        print(f"    intended_action: {item.intended_action}")


def generate_scan_first_summary(
    candidate: BackfillCandidate,
    *,
    api_key: str,
    model: str,
) -> GeneratedBackfillSummary:
    from app.services.summarization import summarize_text

    result = summarize_text(
        candidate.transcript,
        video_title=candidate.title,
        api_key=api_key,
        model=model,
        record_usage_enabled=False,
        video_duration_seconds=candidate.duration_seconds,
    )
    return GeneratedBackfillSummary(
        summary=result["summary"],
        model=result.get("model"),
        prompt_tokens=result.get("prompt_tokens"),
        completion_tokens=result.get("completion_tokens"),
    )


def regenerate_video_report_artifact(db, video_uuid: uuid.UUID):
    from app.services.reporting import generate_video_report

    return generate_video_report(db, video_uuid, commit=False)


def apply_backfill_item(
    db,
    item: BackfillPlanItem,
    *,
    api_key: str,
    model: str,
    allow_malformed: bool = False,
) -> AppliedBackfillResult:
    from app.models.summary import Summary

    candidate = item.candidate
    video_uuid = uuid.UUID(str(candidate.video_uuid))
    generated = generate_scan_first_summary(candidate, api_key=api_key, model=model)
    quality = validate_summary_contract(
        generated.summary,
        word_count=candidate.effective_word_count,
        duration_seconds=candidate.duration_seconds,
    )
    if quality.is_malformed and not allow_malformed:
        raise SummaryValidationError(candidate.youtube_video_id, quality)

    summary = db.query(Summary).filter(Summary.video_id == video_uuid).first()
    if summary is None:
        summary = Summary(video_id=video_uuid, content=generated.summary)
        db.add(summary)
    summary.content = generated.summary
    summary.model = generated.model
    summary.prompt_tokens = generated.prompt_tokens
    summary.completion_tokens = generated.completion_tokens
    db.flush()

    report = regenerate_video_report_artifact(db, video_uuid)
    db.commit()

    return AppliedBackfillResult(
        youtube_video_id=candidate.youtube_video_id,
        title=candidate.title,
        summary_chars=len(generated.summary.strip()),
        prompt_tokens=generated.prompt_tokens,
        completion_tokens=generated.completion_tokens,
        report_path=getattr(report, "artifact_path", None),
        validation_warnings=quality.warnings,
        validation_errors=quality.errors,
    )


def print_apply_result(index: int, total: int, result: AppliedBackfillResult) -> None:
    print(f"\n[{index}/{total}] updated {result.youtube_video_id} — {result.title}")
    print(f"    summary_chars: {result.summary_chars}")
    print(f"    prompt_tokens: {result.prompt_tokens if result.prompt_tokens is not None else 'unknown'}")
    print(f"    completion_tokens: {result.completion_tokens if result.completion_tokens is not None else 'unknown'}")
    print(f"    report_path: {result.report_path or 'unknown'}")
    for error in result.validation_errors:
        print(f"    validation_error: {error}")
    for warning in result.validation_warnings:
        print(f"    validation_warning: {warning}")


def load_backfill_candidates_from_db(
    db,
    *,
    youtube_ids: Sequence[str] | None = None,
    channel: str | None = None,
    since: datetime | None = None,
    completed_only: bool = True,
    limit: int | None = 10,
) -> list[BackfillCandidate]:
    from sqlalchemy import or_

    from app.models.channel import Channel
    from app.models.summary import Summary
    from app.models.transcription import Transcription
    from app.models.video import Video

    normalized_ids = parse_youtube_id_args(youtube_ids)
    query = (
        db.query(Video, Transcription, Summary, Channel)
        .join(Transcription, Transcription.video_id == Video.id)
        .outerjoin(Summary, Summary.video_id == Video.id)
        .outerjoin(Channel, Channel.id == Video.channel_id)
        .filter(Transcription.full_text.isnot(None))
        .filter(Transcription.full_text != "")
    )
    if completed_only:
        query = query.filter(Video.status == "completed")
    if normalized_ids:
        query = query.filter(Video.youtube_video_id.in_(normalized_ids))
    if channel:
        channel_value = channel.strip()
        query = query.filter(
            or_(
                Channel.name.ilike(f"%{channel_value}%"),
                Channel.youtube_channel_id == channel_value,
            )
        )
    since_utc = _aware_utc(since)
    if since_utc:
        query = query.filter(Transcription.created_at >= since_utc)

    query = query.order_by(Transcription.created_at.desc())
    if limit is not None:
        query = query.limit(limit)

    rows = query.all()
    candidates = [
        BackfillCandidate(
            video_uuid=str(video.id),
            youtube_video_id=video.youtube_video_id,
            title=video.title,
            channel_name=channel_row.name if channel_row else None,
            status=video.status,
            transcript=transcription.full_text,
            channel_youtube_id=channel_row.youtube_channel_id if channel_row else None,
            duration_seconds=video.duration_seconds,
            word_count=transcription.word_count,
            existing_summary=summary.content if summary else None,
            summary_model=summary.model if summary else None,
            summary_created_at=summary.created_at if summary else None,
            transcription_created_at=transcription.created_at,
            published_at=video.published_at,
        )
        for video, transcription, summary, channel_row in rows
    ]

    # Keep an in-memory pass as a backstop for tests/fakes and to guarantee
    # comma/URL normalization semantics match the public helper.
    return filter_candidates(
        candidates,
        youtube_ids=normalized_ids,
        channel=channel,
        since=since_utc,
        completed_only=completed_only,
        limit=limit,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dry-run or limited-live backfill of T015 scan-first summaries from completed transcriptions."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum videos to inspect/update, ordered by newest transcription first (default: 10).",
    )
    parser.add_argument(
        "--youtube-id",
        action="append",
        default=[],
        help="Specific YouTube video ID or URL. Repeat or use comma-separated values.",
    )
    parser.add_argument("--channel", help="Filter by channel name substring or exact YouTube channel ID.")
    parser.add_argument(
        "--since",
        help="Only include videos whose transcription row was created on/after YYYY-MM-DD or ISO datetime.",
    )
    parser.add_argument(
        "--include-non-completed",
        action="store_true",
        help="Include videos not marked status=completed. Default is completed-only.",
    )
    parser.add_argument("--db-url", help="Override sync PostgreSQL URL for reads/writes.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Allow DB writes. Requires --generate and --confirm-apply.",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Allow Anthropic calls. Only valid with --apply --confirm-apply for this backfill script.",
    )
    parser.add_argument(
        "--confirm-apply",
        action="store_true",
        help="Operator confirmation required for live backfill writes.",
    )
    parser.add_argument(
        "--allow-malformed",
        action="store_true",
        help="Documented operator override: allow live writes even when deterministic scan-first validation reports hard errors.",
    )
    parser.add_argument("--api-key", default=os.environ.get("ANTHROPIC_API_KEY", ""), help="Anthropic API key for live apply.")
    parser.add_argument("--model", default=None, help="Anthropic summary model override for live apply.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        since = parse_since_datetime(args.since)
    except ValueError as exc:
        parser.error(str(exc))

    errors = validate_requested_mode(
        apply=args.apply,
        generate=args.generate,
        confirm_apply=args.confirm_apply,
        limit=args.limit,
    )
    if errors:
        parser.error("; ".join(errors))

    youtube_ids = parse_youtube_id_args(args.youtube_id)
    completed_only = not args.include_non_completed
    filters_label = _filters_label(
        limit=args.limit,
        youtube_ids=youtube_ids,
        channel=args.channel,
        since=since,
        completed_only=completed_only,
    )

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    db_url = resolve_db_url_sync(args.db_url)
    engine = create_engine(db_url)
    with Session(engine) as db:
        candidates = load_backfill_candidates_from_db(
            db,
            youtube_ids=youtube_ids,
            channel=args.channel,
            since=since,
            completed_only=completed_only,
            limit=args.limit,
        )
        plan = build_backfill_plan(candidates)
        live_apply = bool(args.apply and args.generate and args.confirm_apply)
        print_backfill_plan(plan, dry_run=not live_apply, filters_label=filters_label)

        if not live_apply:
            return 0 if plan else 1

        if not args.api_key:
            parser.error("live backfill requires ANTHROPIC_API_KEY or --api-key")
        model = args.model
        if not model:
            from app.config import settings

            model = settings.summary_model

        total_prompt = 0
        total_completion = 0
        failures = 0
        for index, item in enumerate(plan, start=1):
            try:
                result = apply_backfill_item(
                    db,
                    item,
                    api_key=args.api_key,
                    model=model,
                    allow_malformed=args.allow_malformed,
                )
            except SummaryValidationError as exc:
                db.rollback()
                failures += 1
                print(f"\n[{index}/{len(plan)}] BLOCKED {item.candidate.youtube_video_id}: {exc}", file=sys.stderr)
                for line in format_summary_quality_messages(exc.result):
                    print(f"    {line}", file=sys.stderr)
                continue
            except Exception as exc:  # noqa: BLE001 — keep batch bounded and visible
                db.rollback()
                failures += 1
                print(f"\n[{index}/{len(plan)}] FAILED {item.candidate.youtube_video_id}: {exc}", file=sys.stderr)
                continue
            total_prompt += result.prompt_tokens or 0
            total_completion += result.completion_tokens or 0
            print_apply_result(index, len(plan), result)

        print("\nUsage totals from summarize_text results:")
        print(f"  prompt_tokens: {total_prompt}")
        print(f"  completion_tokens: {total_completion}")
        print(f"  failures: {failures}")
        return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
