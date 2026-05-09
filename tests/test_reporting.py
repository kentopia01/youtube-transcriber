from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from app.models.channel import Channel
from app.models.summary import Summary
from app.models.transcription import Transcription
from app.models.transcription_segment import TranscriptionSegment
from app.models.video import Video
from app.models.video_report import VideoReport
from app.services.reporting import (
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
## Main Topics
- AI increases SDR throughput.
- Proprietary data moats matter.
- Variable comp is returning.
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


def _segment(transcription_id, index=0, text="Hello world", speaker="SPEAKER_00"):
    return SimpleNamespace(
        transcription_id=transcription_id,
        segment_index=index,
        start_time=65.0 + index,
        end_time=70.0 + index,
        text=text,
        speaker=speaker,
    )


class _Query:
    def __init__(self, items):
        self.items = items

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return self.items


class _FakeSession:
    def __init__(self, *, video, channel, summary, transcription, segments):
        self.video = video
        self.channel = channel
        self.summary = summary
        self.transcription = transcription
        self.segments = segments
        self.reports = []
        self.commits = 0

    def get(self, model, item_id):
        if model is Video:
            return self.video if self.video.id == item_id else None
        if model is Channel:
            return self.channel if self.channel.id == item_id else None
        return None

    def query(self, model):
        if model is Transcription:
            return _Query([self.transcription])
        if model is Summary:
            return _Query([self.summary] if self.summary else [])
        if model is TranscriptionSegment:
            return _Query(self.segments)
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


def test_build_report_render_data_defaults_to_summary_only(monkeypatch):
    monkeypatch.setattr("app.services.reporting.settings.report_include_full_transcript", False)
    video = _video()
    transcription = _transcription(video.id)
    data = build_report_render_data(
        video=video,
        channel=_channel(video.channel_id),
        summary=_summary(video.id),
        transcription=transcription,
        segments=[_segment(transcription.id, text="Segment one")],
    )

    assert data.title == "The AI Sales Stack"
    assert data.channel_name == "20VC"
    assert data.duration == "1h 1m"
    assert any("AI increases SDR throughput" in point for point in data.key_points)
    assert data.transcript_paragraphs == []


def test_build_report_render_data_can_include_transcript_when_enabled(monkeypatch):
    monkeypatch.setattr("app.services.reporting.settings.report_include_full_transcript", True)
    video = _video()
    transcription = _transcription(video.id)
    data = build_report_render_data(
        video=video,
        channel=_channel(video.channel_id),
        summary=_summary(video.id),
        transcription=transcription,
        segments=[_segment(transcription.id, text="Segment one")],
    )

    assert data.transcript_paragraphs[0]["time"] == "01:05"
    assert data.transcript_paragraphs[0]["text"] == "Segment one"


def test_render_video_report_html_is_self_contained(monkeypatch):
    monkeypatch.setattr("app.services.reporting.settings.report_include_full_transcript", False)
    video = _video()
    transcription = _transcription(video.id)
    data = build_report_render_data(
        video=video,
        channel=_channel(video.channel_id),
        summary=_summary(video.id),
        transcription=transcription,
        segments=[_segment(transcription.id, text="Transcript segment")],
    )

    html = render_video_report_html(data)

    assert "<!DOCTYPE html>" in html
    assert "<style>" in html
    assert "The AI Sales Stack" in html
    assert "30-second scan" in html
    assert "Source" in html
    assert "Open original YouTube video" in html
    assert html.index("Source") < html.index("30-second scan")
    assert "Key takeaways" in html
    assert "Transcript Appendix" not in html
    assert "Transcript segment" not in html


def test_generate_video_report_writes_artifact_and_upserts(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.reporting.settings.report_artifact_dir", str(tmp_path))
    monkeypatch.setattr("app.services.reporting.settings.report_include_full_transcript", False)
    video = _video()
    channel = _channel(video.channel_id)
    summary = _summary(video.id)
    transcription = _transcription(video.id)
    segments = [_segment(transcription.id, text="Stored transcript segment")]
    db = _FakeSession(
        video=video,
        channel=channel,
        summary=summary,
        transcription=transcription,
        segments=segments,
    )

    report = generate_video_report(db, video.id)

    assert db.commits == 1
    assert report in db.reports
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
    assert "Stored transcript segment" not in text
    assert "Transcript Appendix" not in text

    report.html_content = "old"
    report2 = generate_video_report(db, video.id)
    assert report2 is report
    assert len(db.reports) == 1
    assert "The AI Sales Stack" in report.html_content
    assert "Stored transcript segment" not in report.markdown_content
