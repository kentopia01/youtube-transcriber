from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from scripts.evaluate_scan_first_summaries import (
    EvalCandidate,
    GeneratedSummary,
    SelectedSample,
    is_low_content_candidate,
    normalize_youtube_id,
    render_eval_markdown,
    select_representative_samples,
    write_eval_outputs,
)


_NOW = datetime(2026, 5, 12, 2, 40, tzinfo=UTC)


def _candidate(
    youtube_id: str,
    title: str,
    *,
    duration_seconds: int | None,
    word_count: int,
    transcript: str | None = None,
    channel_name: str | None = "Test Channel",
    existing_summary: str | None = None,
) -> EvalCandidate:
    if transcript is None:
        transcript = " ".join(f"word{i}" for i in range(word_count))
    return EvalCandidate(
        video_uuid=f"uuid-{youtube_id}",
        youtube_video_id=youtube_id,
        title=title,
        channel_name=channel_name,
        duration_seconds=duration_seconds,
        word_count=word_count,
        transcript=transcript,
        existing_summary=existing_summary or "Old summary about broad main topics and generic takeaways.",
        summary_model="claude-old",
        transcription_created_at=_NOW,
    )


def test_normalize_youtube_id_accepts_urls_and_raw_ids():
    assert normalize_youtube_id("abc123XYZ") == "abc123XYZ"
    assert normalize_youtube_id("https://www.youtube.com/watch?v=abc123XYZ&t=30s") == "abc123XYZ"
    assert normalize_youtube_id("https://youtu.be/abc123XYZ?si=test") == "abc123XYZ"
    assert normalize_youtube_id("https://www.youtube.com/shorts/abc123XYZ") == "abc123XYZ"


def test_select_representative_samples_covers_default_categories_when_available():
    candidates = [
        _candidate(
            "long001",
            "Full podcast conversation with an AI founder",
            duration_seconds=5400,
            word_count=9000,
        ),
        _candidate(
            "short001",
            "Three minute GTM clip",
            duration_seconds=210,
            word_count=420,
        ),
        _candidate(
            "review001",
            "Claude Code AI product review and hands-on demo",
            duration_seconds=900,
            word_count=1800,
        ),
        _candidate(
            "low001",
            "Music placeholder upload",
            duration_seconds=60,
            word_count=12,
            transcript="[Music]\n[Music]\n[Music]",
        ),
    ]

    samples = select_representative_samples(candidates)

    assert [sample.category for sample in samples] == [
        "long_podcast",
        "short_clip",
        "ai_product_review",
        "low_content",
    ]
    assert [sample.candidate.youtube_video_id for sample in samples] == [
        "long001",
        "short001",
        "review001",
        "low001",
    ]


def test_select_representative_samples_respects_explicit_ids_and_can_include_defaults():
    explicit = _candidate("manual001", "Manual request", duration_seconds=800, word_count=1200)
    long = _candidate("long001", "Podcast episode", duration_seconds=4200, word_count=7000)
    short = _candidate("short001", "Short useful clip", duration_seconds=240, word_count=360)

    explicit_only = select_representative_samples(
        [explicit, long, short],
        explicit_youtube_ids=["https://www.youtube.com/watch?v=manual001"],
    )
    with_defaults = select_representative_samples(
        [explicit, long, short],
        explicit_youtube_ids=["manual001"],
        include_defaults=True,
        max_samples=3,
    )

    assert [sample.category for sample in explicit_only] == ["explicit"]
    assert [sample.candidate.youtube_video_id for sample in explicit_only] == ["manual001"]
    assert [sample.candidate.youtube_video_id for sample in with_defaults] == [
        "manual001",
        "long001",
        "short001",
    ]


def test_low_content_detection_catches_repeated_marker_transcripts():
    candidate = _candidate(
        "low001",
        "Placeholder",
        duration_seconds=90,
        word_count=120,
        transcript="thank you for watching\n" * 12,
    )

    assert is_low_content_candidate(candidate)


def test_render_eval_markdown_includes_required_metadata_and_summaries():
    candidate = _candidate(
        "review001",
        "Claude Code AI product review",
        duration_seconds=600,
        word_count=1500,
        transcript="The speaker argues the product changes developer workflow with concrete examples.",
        existing_summary="## Main Topics\n- AI tooling\n- Developer workflow",
    )
    sample = SelectedSample("ai_product_review", candidate, "AI/product/review-oriented sample")
    generated = GeneratedSummary(
        summary="## 30-second take\nThe product is useful but needs guardrails.\n\n## Key takes\n- It speeds up code review when paired with tests.",
        model="claude-sonnet-4-5",
        prompt_tokens=100,
        completion_tokens=50,
    )

    markdown = render_eval_markdown(
        sample,
        generated=generated,
        prompt_model="claude-sonnet-4-5",
        generated_at=_NOW,
    )

    assert "# Scan-first summary eval: Claude Code AI product review" in markdown
    assert "- Category: `ai_product_review`" in markdown
    assert "- Word count: 1500" in markdown
    assert "## Existing summary excerpt" in markdown
    assert "AI tooling" in markdown
    assert "## Generated scan-first summary" in markdown
    assert "The product is useful but needs guardrails" in markdown
    assert "## Contract validation" in markdown
    assert "missing required heading" in markdown
    assert "- Production summary DB writes: none" in markdown
    assert "Prompt tokens: 100" in markdown


def test_eval_generation_can_disable_cost_tracker_db_writes(monkeypatch):
    from app.services import summarization

    usage_calls = []

    def fake_anthropic_call(client, **kwargs):
        return SimpleNamespace(
            content=[SimpleNamespace(text="## 30-second take\nGenerated")],
            usage=SimpleNamespace(input_tokens=11, output_tokens=7),
        )

    def fake_record_usage(*args, **kwargs):
        usage_calls.append((args, kwargs))

    monkeypatch.setattr(summarization, "_call_anthropic_with_retry", fake_anthropic_call)
    monkeypatch.setattr("app.services.cost_tracker.record_usage", fake_record_usage)

    result = summarization._summarize_single(
        object(),
        "claude-test",
        "transcript",
        "title",
        record_usage_enabled=False,
    )

    assert result["summary"] == "## 30-second take\nGenerated"
    assert result["prompt_tokens"] == 11
    assert result["completion_tokens"] == 7
    assert usage_calls == []


def test_write_eval_outputs_creates_index_and_sample_markdown(tmp_path):
    candidate = _candidate(
        "review001",
        "Claude Code AI product review",
        duration_seconds=600,
        word_count=1500,
    )
    sample = SelectedSample("ai_product_review", candidate, "AI/product/review-oriented sample")
    generated = GeneratedSummary(summary="## 30-second take\nUseful scan-first result.", model="claude")

    written = write_eval_outputs(
        [sample],
        generated_by_youtube_id={"review001": generated},
        output_dir=tmp_path,
        prompt_model="claude",
        generated_at=_NOW,
    )

    assert (tmp_path / "index.md") in written
    index = (tmp_path / "index.md").read_text()
    assert "T015 scan-first summary evaluation" in index
    assert "review001" in index

    sample_paths = [path for path in written if path.name != "index.md"]
    assert len(sample_paths) == 1
    assert "Useful scan-first result" in sample_paths[0].read_text()
