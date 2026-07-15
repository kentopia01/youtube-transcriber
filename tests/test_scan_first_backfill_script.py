from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.summary import Summary
from scripts import backfill_scan_first_summaries as mod


_NOW = datetime(2026, 5, 12, 3, 0, tzinfo=UTC)


def _candidate(
    youtube_id: str,
    title: str = "Test video",
    *,
    channel_name: str | None = "Test Channel",
    status: str = "completed",
    word_count: int = 500,
    transcript: str | None = None,
    existing_summary: str | None = "old summary",
    summary_created_at: datetime | None = None,
    transcription_created_at: datetime | None = None,
) -> mod.BackfillCandidate:
    return mod.BackfillCandidate(
        video_uuid=str(uuid.uuid4()),
        youtube_video_id=youtube_id,
        title=title,
        channel_name=channel_name,
        status=status,
        transcript=transcript or " ".join(f"word{i}" for i in range(word_count)),
        word_count=word_count,
        existing_summary=existing_summary,
        summary_model="claude-old" if existing_summary else None,
        summary_created_at=summary_created_at or (_NOW - timedelta(days=4) if existing_summary else None),
        transcription_created_at=transcription_created_at or _NOW,
    )


def _valid_summary() -> str:
    return """
## At-a-Glance
- Verdict: Skim
- Core thesis: The speaker argues AI ops teams should use agents to remove repeatable workflow drag while keeping evals and human review in place.
- Why it matters: Ken can turn the pattern into agent systems and GTM workflows.
- Best use: Skim for the operating pattern.

## Executive Summary
The speaker argues AI ops teams should use agents to remove repeatable workflow drag while keeping evals and human review in place.

The useful point for Ken is that agents create leverage when they automate a specific workflow instead of becoming a generic chatbot, and when quality checks remain attached to the system.

## Key Takeaways
- Claim: Agents create leverage when they automate a specific workflow instead of becoming a generic chatbot. | Evidence: The video mentions agent handoffs and workflow boundaries. | Caveat: It does not prove every workflow benefits. | Implication: Ken should start with bounded agent systems.
- Claim: AI ops needs evals because unchecked automation can silently lower quality. | Evidence: The transcript names evals and human review. | Caveat: Eval design still requires judgement. | Implication: Ken should attach evals to every automated workflow.
- Claim: Content and GTM teams can reuse the same workflow to turn research into sales opportunities. | Evidence: GTM workflows are listed as a concrete use case. | Caveat: The output depends on input quality. | Implication: Ken can connect content intelligence to business opportunities.
- Claim: Ken should treat the idea as an operating pattern rather than a standalone product recommendation. | Evidence: The speaker emphasizes workflow, handoffs, evals, and review. | Caveat: Tooling still affects implementation. | Implication: Ken should port the pattern across personal workflow and AI ops.

## Detailed Brief
### Agent workflow
- Claims: Agent workflows work when scoped.
- Evidence: The video mentions agent handoffs, evals, GTM workflows, and human review.
- Caveats: The transcript does not prove this works for every team or every workflow.
- Implications: Ken should choose bounded workflows first.

### Quality guardrail
- Claims: Evals protect agent output quality.
- Evidence: Human review and evals are named together.
- Caveats: Bad evals can give false confidence.
- Implications: Ken should keep quality evidence attached to agent outputs.

### GTM reuse
- Claims: Content and sales workflows can share the same agent pattern.
- Evidence: GTM workflows are named as a use case.
- Caveats: Source data quality matters.
- Implications: Ken can reuse transcript intelligence for content/business opportunities.

## Notable Concepts & Terms
- Agent handoff: Context transfer between tools or agents.
- Eval: A deterministic or model-assisted quality check.
- GTM workflow: Repeatable content/sales process.
- Human review: Manual guardrail for high-risk outputs.

## Operator Notes / Why Ken Should Care
- Relevant to Ken's agent systems, AI ops, content/business opportunities, investing, GTM, and personal workflow.

## Source/Metadata
- Title: Backfill sample
- Transcript words: 1200
- Timestamp note: Timestamps or chapters were unavailable in the transcript.
""".strip()


def test_parse_youtube_id_args_accepts_repeatable_comma_and_urls():
    parsed = mod.parse_youtube_id_args(
        [
            "abc123, https://youtu.be/def456?si=x",
            "https://www.youtube.com/watch?v=ghi789&t=30s",
            "abc123",
        ]
    )

    assert parsed == ["abc123", "def456", "ghi789"]


def test_parse_since_datetime_normalizes_date_and_iso_values():
    assert mod.parse_since_datetime("2026-05-12") == datetime(2026, 5, 12, tzinfo=UTC)
    assert mod.parse_since_datetime("2026-05-12T10:30:00+08:00") == datetime(2026, 5, 12, 2, 30, tzinfo=UTC)


def test_filter_candidates_respects_completed_channel_since_youtube_ids_and_limit():
    recent_ai = _candidate(
        "keep001",
        "Recent AI video",
        channel_name="AI Ops Channel",
        transcription_created_at=_NOW,
    )
    old_ai = _candidate(
        "old001",
        "Old AI video",
        channel_name="AI Ops Channel",
        transcription_created_at=_NOW - timedelta(days=20),
    )
    wrong_channel = _candidate(
        "other001",
        "Other channel",
        channel_name="Cooking Channel",
        transcription_created_at=_NOW,
    )
    not_completed = _candidate(
        "active001",
        "Still summarizing",
        channel_name="AI Ops Channel",
        status="summarizing",
        transcription_created_at=_NOW,
    )

    filtered = mod.filter_candidates(
        [recent_ai, old_ai, wrong_channel, not_completed],
        youtube_ids=["keep001,old001,other001,active001"],
        channel="ai ops",
        since=_NOW - timedelta(days=1),
        completed_only=True,
        limit=1,
    )

    assert filtered == [recent_ai]


def test_build_plan_and_dry_run_output_include_required_fields(capsys):
    candidate = _candidate(
        "vid001",
        "Concrete AI ops takeaways",
        channel_name="Ops Lab",
        word_count=1234,
        existing_summary="existing summary text",
        summary_created_at=_NOW - timedelta(days=3),
    )
    plan = mod.build_backfill_plan([candidate])

    mod.print_backfill_plan(plan, dry_run=True, filters_label="completed_only=True limit=1", now=_NOW)
    output = capsys.readouterr().out

    assert "Mode: DRY RUN" in output
    assert "no Anthropic calls and no DB writes" in output
    assert "vid001" in output
    assert "Concrete AI ops takeaways" in output
    assert "Ops Lab" in output
    assert "word_count: 1234" in output
    assert "existing_summary: 3d old" in output
    assert "intended_action: replace summary; regenerate summary_report artifact" in output


def test_plan_marks_missing_summary_as_create_action():
    candidate = _candidate("vid002", existing_summary=None)

    plan = mod.build_backfill_plan([candidate])

    assert plan[0].intended_action == "create summary; generate summary_report artifact"
    assert mod.existing_summary_label(candidate, now=_NOW) == "none"


def test_validate_requested_mode_enforces_safety_gates():
    assert mod.validate_requested_mode(apply=False, generate=False, confirm_apply=False, limit=10) == []
    assert mod.validate_requested_mode(apply=False, generate=True, confirm_apply=False, limit=10) == [
        "--generate is only allowed with --apply; use the eval harness for local generated samples"
    ]
    assert mod.validate_requested_mode(apply=True, generate=False, confirm_apply=True, limit=10) == [
        "--apply requires --generate so DB writes cannot happen without an explicit Anthropic opt-in"
    ]
    assert mod.validate_requested_mode(apply=True, generate=True, confirm_apply=False, limit=10) == [
        "live backfill requires --confirm-apply in addition to --apply --generate"
    ]
    assert "--limit must be greater than 0" in mod.validate_requested_mode(
        apply=False,
        generate=False,
        confirm_apply=False,
        limit=0,
    )


def test_generate_scan_first_summary_disables_cost_tracker_writes(monkeypatch):
    candidate = _candidate("vid003", transcript="real transcript", word_count=2)
    calls = []

    def fake_summarize_text(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "summary": "## 30-second take\nUseful.",
            "model": "claude-test",
            "prompt_tokens": 11,
            "completion_tokens": 7,
        }

    monkeypatch.setattr("app.services.summarization.summarize_text", fake_summarize_text)

    result = mod.generate_scan_first_summary(candidate, api_key="key", model="claude-test")

    assert result.summary.startswith("## 30-second take")
    assert result.prompt_tokens == 11
    assert result.completion_tokens == 7
    assert calls[0][1]["record_usage_enabled"] is False


class _SummaryQuery:
    def __init__(self, db):
        self.db = db

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.db.summary


class _FakeDb:
    def __init__(self, summary=None):
        self.summary = summary
        self.added = []
        self.flushed = 0
        self.committed = 0

    def query(self, model):
        assert model is Summary
        return _SummaryQuery(self)

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, Summary):
            self.summary = obj

    def flush(self):
        self.flushed += 1

    def commit(self):
        self.committed += 1


def test_apply_backfill_item_upserts_summary_and_regenerates_report(monkeypatch):
    video_uuid = uuid.uuid4()
    candidate = mod.BackfillCandidate(
        video_uuid=str(video_uuid),
        youtube_video_id="vid004",
        title="Backfill me",
        channel_name="Ops Lab",
        status="completed",
        transcript="substantive transcript",
        word_count=2,
    )
    db = _FakeDb()
    regenerated = []

    monkeypatch.setattr(
        mod,
        "generate_scan_first_summary",
        lambda candidate, api_key, model: mod.GeneratedBackfillSummary(
            summary=_valid_summary(),
            model=model,
            prompt_tokens=101,
            completion_tokens=55,
        ),
    )

    def fake_regenerate(db_arg, video_uuid_arg):
        regenerated.append((db_arg, video_uuid_arg))
        return SimpleNamespace(artifact_path="/tmp/report.html")

    monkeypatch.setattr(mod, "regenerate_video_report_artifact", fake_regenerate)

    result = mod.apply_backfill_item(db, mod.BackfillPlanItem(candidate, "create"), api_key="key", model="claude-test")

    assert isinstance(db.summary, Summary)
    assert db.summary.video_id == video_uuid
    assert db.summary.content == _valid_summary()
    assert db.summary.model == "claude-test"
    assert db.summary.prompt_tokens == 101
    assert db.summary.completion_tokens == 55
    assert regenerated == [(db, video_uuid)]
    assert db.flushed == 1
    assert db.committed == 1
    assert result.report_path == "/tmp/report.html"
    assert result.prompt_tokens == 101
    assert result.completion_tokens == 55
    assert result.validation_errors == ()


def test_apply_backfill_item_blocks_malformed_summary_before_db_write(monkeypatch):
    video_uuid = uuid.uuid4()
    candidate = mod.BackfillCandidate(
        video_uuid=str(video_uuid),
        youtube_video_id="vid005",
        title="Malformed backfill",
        channel_name="Ops Lab",
        status="completed",
        transcript="substantive transcript",
        word_count=1200,
    )
    db = _FakeDb()
    regenerated = []

    monkeypatch.setattr(
        mod,
        "generate_scan_first_summary",
        lambda candidate, api_key, model: mod.GeneratedBackfillSummary(
            summary="## 30-second take\nGeneric output without the required contract.",
            model=model,
            prompt_tokens=11,
            completion_tokens=7,
        ),
    )
    monkeypatch.setattr(mod, "regenerate_video_report_artifact", lambda *args: regenerated.append(args))

    with pytest.raises(mod.SummaryValidationError) as exc:
        mod.apply_backfill_item(db, mod.BackfillPlanItem(candidate, "replace"), api_key="key", model="claude-test")

    assert "failed scan-first validation" in str(exc.value)
    assert db.summary is None
    assert db.added == []
    assert db.flushed == 0
    assert db.committed == 0
    assert regenerated == []


def test_apply_backfill_item_blocks_false_positive_low_content_before_db_write(monkeypatch):
    video_uuid = uuid.uuid4()
    candidate = mod.BackfillCandidate(
        video_uuid=str(video_uuid),
        youtube_video_id="vid_false_low",
        title="False low-content backfill",
        channel_name="Ops Lab",
        status="completed",
        transcript="substantive transcript",
        word_count=1200,
    )
    db = _FakeDb()
    regenerated = []

    false_positive_summary = """
## 30-second take
The speaker gives a substantive licensing strategy for AI-generated music products and creator workflows.

## Key takes
- AI music products need licensing clarity before GTM scale.

## Useful details
- The video discusses rights, product strategy, and workflow automation.

## Caveats / counterpoints
- It does not prove the licensing approach will work in every market.

## Ken relevance
- Relevant to Ken's agent systems and AI ops workflow, and this is not a low-content transcript.

## Watch verdict
Skim — useful enough for the product strategy angle.
""".strip()

    monkeypatch.setattr(
        mod,
        "generate_scan_first_summary",
        lambda candidate, api_key, model: mod.GeneratedBackfillSummary(
            summary=false_positive_summary,
            model=model,
            prompt_tokens=11,
            completion_tokens=7,
        ),
    )
    monkeypatch.setattr(mod, "regenerate_video_report_artifact", lambda *args: regenerated.append(args))

    with pytest.raises(mod.SummaryValidationError) as exc:
        mod.apply_backfill_item(db, mod.BackfillPlanItem(candidate, "replace"), api_key="key", model="claude-test")

    assert "expected at least 4" in str(exc.value.result.errors)
    assert not exc.value.result.is_low_content
    assert db.summary is None
    assert db.added == []
    assert db.flushed == 0
    assert db.committed == 0
    assert regenerated == []


def test_apply_backfill_item_allows_documented_malformed_override(monkeypatch):
    video_uuid = uuid.uuid4()
    candidate = mod.BackfillCandidate(
        video_uuid=str(video_uuid),
        youtube_video_id="vid006",
        title="Override backfill",
        channel_name="Ops Lab",
        status="completed",
        transcript="substantive transcript",
        word_count=1200,
    )
    db = _FakeDb()

    monkeypatch.setattr(
        mod,
        "generate_scan_first_summary",
        lambda candidate, api_key, model: mod.GeneratedBackfillSummary(
            summary="## 30-second take\nGeneric output without the required contract.",
            model=model,
            prompt_tokens=11,
            completion_tokens=7,
        ),
    )
    monkeypatch.setattr(
        mod,
        "regenerate_video_report_artifact",
        lambda db_arg, video_uuid_arg: SimpleNamespace(artifact_path="/tmp/override.html"),
    )

    result = mod.apply_backfill_item(
        db,
        mod.BackfillPlanItem(candidate, "replace"),
        api_key="key",
        model="claude-test",
        allow_malformed=True,
    )

    assert db.committed == 1
    assert result.report_path == "/tmp/override.html"
    assert result.validation_errors
