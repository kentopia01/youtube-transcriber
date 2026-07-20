from pathlib import Path

import pytest

from scripts.evaluate_global_search import (
    QueryCase,
    Variant,
    aggregate_variant,
    load_query_cases,
    ranked_video_ids,
    render_markdown,
    run_benchmark,
    score_query,
)


def _case() -> QueryCase:
    return QueryCase("q1", "name", "find the speaker", ("expected",))


def _variant() -> Variant:
    return Variant("baseline", 12, 100, 50, 3)


def test_committed_query_set_is_valid_and_covers_required_categories():
    cases = load_query_cases(Path("benchmarks/global_search_queries.json"))

    assert len(cases) >= 10
    assert {case.category for case in cases} == {
        "name",
        "technical_term",
        "broad_theme",
        "vague_question",
        "summary_style",
    }


def test_ranked_video_ids_deduplicates_chunks_from_the_same_video():
    results = [
        {"youtube_video_id": "a"},
        {"youtube_video_id": "a"},
        {"youtube_video_id": "b"},
        {"youtube_video_id": None},
    ]

    assert ranked_video_ids(results) == ["a", "b"]


def test_score_query_uses_first_relevant_video_rank_and_recall():
    case = QueryCase("q", "theme", "query", ("target", "also-target"))

    score = score_query(
        case,
        [
            {"youtube_video_id": "other"},
            {"youtube_video_id": "target"},
            {"youtube_video_id": "target"},
        ],
    )

    assert score["hit"] is True
    assert score["first_relevant_rank"] == 2
    assert score["reciprocal_rank"] == 0.5
    assert score["recall"] == 0.5
    assert score["distinct_videos"] == 2


def test_run_benchmark_repeats_latency_but_scores_each_query_once():
    calls = []

    def fake_search(case, variant):
        calls.append((case.id, variant.name))
        return {"results": [{"youtube_video_id": "expected"}]}, 10.0

    reports = run_benchmark([_case()], [_variant()], fake_search, repeat=3)

    assert len(calls) == 3
    assert reports[0]["hit_rate"] == 1.0
    assert reports[0]["mrr"] == 1.0
    assert reports[0]["latency_ms"]["samples"] == 3


def test_run_benchmark_rejects_zero_repetitions():
    with pytest.raises(ValueError, match="repeat"):
        run_benchmark([_case()], [_variant()], lambda *_: ({"results": []}, 1.0), repeat=0)


def test_markdown_report_shows_metrics_and_misses():
    miss = score_query(_case(), [{"youtube_video_id": "other"}])
    variant_report = aggregate_variant(_variant(), [miss], [10.0, 20.0])
    report = {
        "generated_at": "2026-07-20T00:00:00+00:00",
        "query_count": 1,
        "repeat": 2,
        "variants": [variant_report],
    }

    markdown = render_markdown(report)

    assert "| baseline | 0.0% |" in markdown
    assert "`baseline` / `q1` expected `expected`" in markdown
