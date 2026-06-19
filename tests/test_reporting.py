from __future__ import annotations

import operator
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from app.models.channel import Channel
from app.models.summary import Summary
from app.models.transcription import Transcription
from app.models.video import Video
from app.models.video_report import SUMMARY_REPORT_TYPE, VideoReport
from app.services.reporting import (
    ReportQualityError,
    build_report_caption,
    build_report_render_data,
    generate_video_report,
    render_video_report_html,
)


_NOW = datetime(2026, 5, 9, 8, 0, tzinfo=UTC)


def _video(video_id=None):
    return SimpleNamespace(
        id=video_id or uuid.uuid4(),
        channel_id=uuid.uuid4(),
        title="The AI Sales Stack",
        url="https://www.youtube.com/watch?v=abc123",
        duration_seconds=3670,
        published_at=_NOW,
    )


def _channel(channel_id):
    return SimpleNamespace(id=channel_id, name="20VC")


def _summary(video_id):
    return SimpleNamespace(
        video_id=video_id,
        content="""
## At-a-Glance
- Verdict: Skim
- Core thesis: The speaker argues AI sales stacks matter because they can turn SDR work from manual prospecting into repeatable leverage.
- Why it matters: Ken can reuse the pattern for agent GTM workflows and internal automation design.
- Best use: Skim for the workflow and incentive pattern.

## Executive Summary
The speaker argues AI sales stacks matter because they can turn SDR work from manual prospecting into repeatable leverage, but only when teams pair automation with proprietary data and clear compensation incentives.

The strongest useful thread is that AI is not valuable because it adds another dashboard; it is valuable when it removes repetitive prospecting work, protects a data moat, and keeps humans accountable for pipeline quality.

## Key Takeaways
- Claim: AI increases SDR throughput when it removes repetitive prospecting work instead of merely adding another dashboard. | Evidence: The speaker ties useful automation to prospecting workflow removal. | Caveat: The summary does not prove every team has the same workflow. | Implication: Ken should automate around known GTM bottlenecks.
- Claim: Proprietary data moats matter because generic automation is easy for competitors to copy. | Evidence: The video contrasts proprietary data with generic tooling. | Caveat: The moat depends on data quality. | Implication: Ken should preserve unique source data in agent GTM workflows.
- Claim: Variable comp is returning because teams still need humans accountable for pipeline quality. | Evidence: The speaker connects compensation incentives with quality ownership. | Caveat: Incentive design can become noisy. | Implication: Ken should keep accountability attached to automated sales loops.
- Claim: AI sales stacks work best when the team already understands its ICP and workflow. | Evidence: The strongest examples are tied to teams with known sales motion. | Caveat: Weak ICP clarity will limit gains. | Implication: Ken should map the workflow before choosing tools.

## Detailed Brief
### SDR leverage
- Claims: AI should remove repetitive prospecting work, not just create another system to check.
- Evidence: The strongest examples are tied to sales teams that already know their ICP and workflow.
- Caveats: The summary does not include proof that every GTM team should automate immediately.
- Implications: Ken should anchor agent work in concrete sales bottlenecks.

### Data moat
- Claims: Proprietary data makes automation more defensible than generic workflow copying.
- Evidence: The speaker distinguishes data ownership from generic automation.
- Caveats: Bad or stale data will collapse the moat.
- Implications: Ken should capture and label GTM source data while building agents.

### Incentives
- Claims: Human accountability and variable comp still matter after automation.
- Evidence: Pipeline quality remains tied to human ownership.
- Caveats: Comp plans can create perverse incentives.
- Implications: Ken should design review loops for agent-assisted GTM.

## Notable Concepts & Terms
- SDR throughput: More useful sales-development output per human rep.
- Proprietary data moat: Data competitors cannot easily copy.
- Variable comp: Incentive pay tied to pipeline or revenue outcomes.
- ICP: The customer profile that defines the sales workflow.

## Operator Notes / Why Ken Should Care
- Relevant for agent GTM workflows and internal automation design.
- Useful for thinking about where agent systems should own tasks versus where humans should stay accountable.

## Watch Map
- timestamp unavailable: Skim the parts on SDR throughput, proprietary data, and compensation incentives.

## Source/Metadata
- Title: The AI Sales Stack
- Transcript words: 320
- Timestamp note: Timestamps or chapters were unavailable in the transcript.
""".strip(),
        model="claude-haiku-4-5-20251001",
        prompt_tokens=100,
        completion_tokens=40,
    )


def _transcription(video_id):
    return SimpleNamespace(
        id=uuid.uuid4(),
        video_id=video_id,
        full_text="Full transcript text here.",
        word_count=320,
    )


def _matches_filter(item, expression):
    left_key = getattr(getattr(expression, "left", None), "key", None)
    right = getattr(expression, "right", None)
    value = getattr(right, "value", None)
    op = getattr(expression, "operator", None)
    if left_key and op is operator.eq:
        return getattr(item, left_key, None) == value
    return True


class _Query:
    def __init__(self, items):
        self.items = items

    def filter(self, *args, **kwargs):
        self.items = [
            item
            for item in self.items
            if all(_matches_filter(item, expression) for expression in args)
        ]
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return self.items


class _FakeSession:
    def __init__(self, *, video, channel, summary, transcription, reports=None):
        self.video = video
        self.channel = channel
        self.summary = summary
        self.transcription = transcription
        self.reports = list(reports or [])
        self.commits = 0

    def get(self, model, item_id):
        if model is Video:
            return self.video if self.video.id == item_id else None
        if model is Channel:
            return self.channel if self.channel and self.channel.id == item_id else None
        return None

    def query(self, model):
        if model is Transcription:
            return _Query([self.transcription] if self.transcription else [])
        if model is Summary:
            return _Query([self.summary] if self.summary else [])
        if model is VideoReport:
            return _Query(self.reports)
        raise AssertionError(f"unexpected model query: {model}")

    def add(self, obj):
        if isinstance(obj, VideoReport):
            self.reports.append(obj)

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        pass

    def flush(self):
        pass


def test_build_report_render_data_is_summary_first():
    video = _video()
    transcription = _transcription(video.id)
    data = build_report_render_data(
        video=video,
        channel=_channel(video.channel_id),
        summary=_summary(video.id),
        transcription=transcription,
    )

    assert data.title == "The AI Sales Stack"
    assert data.channel_name == "20VC"
    assert data.duration == "1h 1m"
    assert data.word_count == 320
    assert "speaker argues AI sales stacks matter" in data.executive_summary_html
    assert "Verdict" in data.at_a_glance_html
    assert data.watch_verdict_html is not None
    assert "Skim" in data.watch_verdict_html
    assert data.ken_relevance_html is not None
    assert "agent GTM workflows" in data.ken_relevance_html
    assert data.detailed_brief_html is not None
    assert "SDR leverage" in data.detailed_brief_html
    assert data.concepts_html is not None
    assert "Proprietary data moat" in data.concepts_html
    assert data.operator_notes_html is not None
    assert data.watch_map_html is not None
    assert data.key_points == [
        "Claim: AI increases SDR throughput when it removes repetitive prospecting work instead of merely adding another dashboard. | Evidence: The speaker ties useful automation to prospecting workflow removal. | Caveat: The summary does not prove every team has the same workflow. | Implication: Ken should automate around known GTM bottlenecks.",
        "Claim: Proprietary data moats matter because generic automation is easy for competitors to copy. | Evidence: The video contrasts proprietary data with generic tooling. | Caveat: The moat depends on data quality. | Implication: Ken should preserve unique source data in agent GTM workflows.",
        "Claim: Variable comp is returning because teams still need humans accountable for pipeline quality. | Evidence: The speaker connects compensation incentives with quality ownership. | Caveat: Incentive design can become noisy. | Implication: Ken should keep accountability attached to automated sales loops.",
        "Claim: AI sales stacks work best when the team already understands its ICP and workflow. | Evidence: The strongest examples are tied to teams with known sales motion. | Caveat: Weak ICP clarity will limit gains. | Implication: Ken should map the workflow before choosing tools.",
    ]


def test_build_report_render_data_allows_missing_transcription():
    video = _video()
    data = build_report_render_data(
        video=video,
        channel=_channel(video.channel_id),
        summary=_summary(video.id),
        transcription=None,
    )

    assert data.word_count is None
    assert "repeatable leverage" in data.executive_summary_html


def test_render_video_report_html_is_self_contained():
    video = _video()
    transcription = _transcription(video.id)
    data = build_report_render_data(
        video=video,
        channel=_channel(video.channel_id),
        summary=_summary(video.id),
        transcription=transcription,
    )

    html = render_video_report_html(data)

    assert "<!DOCTYPE html>" in html
    assert "<style>" in html
    assert "The AI Sales Stack" in html
    assert "At-a-Glance" in html
    assert "Executive Summary" in html
    assert "speaker argues AI sales stacks matter" in html
    assert "Source" in html
    assert "Open original YouTube video" in html
    assert "Detailed Brief" in html
    assert "Notable Concepts &amp; Terms" in html
    assert "Operator Notes / Why Ken Should Care" in html
    assert "Watch Map" in html
    assert html.index("At-a-Glance") < html.index("Executive Summary")
    assert html.index("Executive Summary") < html.index("Key Takeaways")
    assert html.index("Key Takeaways") < html.index("Detailed Brief")
    assert html.index("Detailed Brief") < html.index("Source/Metadata")
    assert "max-width:390px" not in html
    assert ".container{width:100%;max-width:none" in html
    assert ".takeaway-list{list-style:none" in html
    assert "Transcript Appendix" not in html
    assert "Full transcript text here" not in html


def test_render_video_report_html_formats_extracted_key_point_markdown():
    video = _video()
    summary = SimpleNamespace(
        video_id=video.id,
        content="""
## 30-second take
Short scan.

## Key takes
- **Important thesis**: `agents` need reliable handoffs.
""".strip(),
        model="claude-haiku-4-5-20251001",
        prompt_tokens=100,
        completion_tokens=40,
    )
    data = build_report_render_data(
        video=video,
        channel=_channel(video.channel_id),
        summary=summary,
        transcription=None,
    )

    html = render_video_report_html(data)

    assert "**Important thesis**" not in html
    assert "<strong>Important thesis</strong>" in html
    assert "<code>agents</code>" in html


def test_generate_video_report_writes_summary_report_artifact_and_upserts(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.reporting.settings.report_artifact_dir", str(tmp_path))
    video = _video()
    channel = _channel(video.channel_id)
    summary = _summary(video.id)
    transcription = _transcription(video.id)
    db = _FakeSession(
        video=video,
        channel=channel,
        summary=summary,
        transcription=transcription,
    )

    report = generate_video_report(db, video.id)

    assert db.commits == 1
    assert report in db.reports
    assert report.report_type == SUMMARY_REPORT_TYPE
    assert report.delivery_status == "pending"
    assert report.model == summary.model
    assert report.artifact_path.endswith("_report.html")
    artifact = Path(report.artifact_path)
    assert artifact.exists()
    assert artifact.is_relative_to(tmp_path)
    text = artifact.read_text()
    assert "The AI Sales Stack" in text
    assert "Source" in text
    assert "Open original YouTube video" in text
    assert "Full transcript text here" not in text
    assert "Transcript Appendix" not in text

    report.html_content = "old"
    report2 = generate_video_report(db, video.id)
    assert report2 is report
    assert len(db.reports) == 1
    assert "The AI Sales Stack" in report.html_content
    assert "Full transcript text here" not in report.markdown_content


def test_generate_video_report_normalizes_existing_report_type_instead_of_creating_variant(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("app.services.reporting.settings.report_artifact_dir", str(tmp_path))
    video = _video()
    summary = _summary(video.id)
    existing_report = VideoReport(
        video_id=video.id,
        report_type="experimental_variant",
        title="Old report",
        html_content="old",
        artifact_path="old.html",
    )
    db = _FakeSession(
        video=video,
        channel=_channel(video.channel_id),
        summary=summary,
        transcription=_transcription(video.id),
        reports=[existing_report],
    )

    report = generate_video_report(db, video.id, commit=False)

    assert report is existing_report
    assert len(db.reports) == 1
    assert report.report_type == SUMMARY_REPORT_TYPE
    assert report.delivery_status == "pending"
    assert report.artifact_path != "old.html"
    assert Path(report.artifact_path).exists()
    assert db.commits == 0


def test_build_report_caption_uses_scan_first_summary():
    caption = build_report_caption(_summary(uuid.uuid4()).content)

    assert caption is not None
    assert "speaker argues AI sales stacks matter" in caption
    assert "AI increases SDR throughput" in caption
    assert "Main Topics" not in caption


def test_generate_video_report_can_use_video_and_summary_without_transcription(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.reporting.settings.report_artifact_dir", str(tmp_path))
    video = _video()
    summary = _summary(video.id)
    db = _FakeSession(
        video=video,
        channel=_channel(video.channel_id),
        summary=summary,
        transcription=None,
    )

    report = generate_video_report(db, video.id)

    assert report.report_type == SUMMARY_REPORT_TYPE
    assert report.model == summary.model
    assert Path(report.artifact_path).exists()
    assert "AI increases SDR throughput" in report.html_content
    assert '<span class="meta-item">320 words</span>' not in report.html_content


def test_generate_video_report_blocks_long_single_paragraph_teaser(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.reporting.settings.report_artifact_dir", str(tmp_path))
    video = _video()
    video.duration_seconds = 759
    thin_summary = SimpleNamespace(
        video_id=video.id,
        content="""
## 30-second take
This is one dense teaser paragraph about a long video but it has no key takeaways, detailed brief, evidence, caveats, operator notes, or watch map.
""".strip(),
        model="claude-sonnet-4-5",
        prompt_tokens=100,
        completion_tokens=40,
    )
    transcription = _transcription(video.id)
    transcription.word_count = 1648
    db = _FakeSession(
        video=video,
        channel=_channel(video.channel_id),
        summary=thin_summary,
        transcription=transcription,
    )

    try:
        generate_video_report(db, video.id)
    except ReportQualityError as exc:
        assert "too thin" in str(exc)
        assert "Key Takeaways" in str(exc)
    else:
        raise AssertionError("expected ReportQualityError")

    assert db.commits == 0
    assert not list(tmp_path.rglob("*.html"))
