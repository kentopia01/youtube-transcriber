"""Tests for whole-corpus global search helpers."""

from types import SimpleNamespace
import uuid

from app.services.embedding import SUMMARY_SPEAKER_LABEL
from app.services.global_search import (
    GlobalSearchOptions,
    _build_global_where_clause,
    _row_to_candidate,
    balance_source_types,
    build_evidence_text,
    build_youtube_url,
    reciprocal_rank_fuse,
    select_diverse_results,
)


def _candidate(candidate_id, video_id, text, score=0.01, source_type="transcript"):
    return {
        "id": str(candidate_id),
        "video_id": str(video_id),
        "chunk_text": text,
        "fused_score": score,
        "score_components": {"vector": score},
        "source_type": source_type,
    }


def test_global_options_are_bounded():
    channel_id = uuid.uuid4()
    opts = GlobalSearchOptions(
        limit=999,
        candidate_limit=999,
        summary_limit=999,
        per_video_limit=999,
        channel_id=channel_id,
        source_type="bad",
        rrf_k=0,
    ).normalized()

    assert opts.limit == 50
    assert opts.candidate_limit == 250
    assert opts.summary_limit == 250
    assert opts.per_video_limit == 50
    assert opts.channel_id == channel_id
    assert opts.source_type == "all"
    assert opts.rrf_k == 1


def test_build_global_where_clause_source_filters():
    clause, params = _build_global_where_clause(source_type="summary")
    assert "ec.speaker = :summary_label" in clause
    assert params["summary_label"] == SUMMARY_SPEAKER_LABEL

    clause, _ = _build_global_where_clause(source_type="transcript")
    assert "ec.speaker IS NULL" in clause


def test_row_to_candidate_marks_summary_and_youtube_url():
    row = SimpleNamespace(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        video_title="A video",
        youtube_video_id="abc123",
        channel_id=uuid.uuid4(),
        channel_name="Channel",
        chunk_text="summary text",
        start_time=12.8,
        end_time=None,
        speaker=SUMMARY_SPEAKER_LABEL,
        similarity=0.9,
    )

    candidate = _row_to_candidate(row, "summary", 1)

    assert candidate["source_type"] == "summary"
    assert candidate["youtube_url"] == "https://www.youtube.com/watch?v=abc123&t=12s"
    assert candidate["lane_ranks"] == {"summary": 1}


def test_reciprocal_rank_fuse_combines_lanes():
    shared_id = uuid.uuid4()
    video_id = uuid.uuid4()
    lanes = {
        "vector": [_candidate(shared_id, video_id, "shared")],
        "keyword": [_candidate(shared_id, video_id, "shared")],
        "summary": [_candidate(uuid.uuid4(), uuid.uuid4(), "other")],
    }

    fused = reciprocal_rank_fuse(lanes, rrf_k=60)

    assert fused[0]["id"] == str(shared_id)
    assert set(fused[0]["score_components"]) == {"vector", "keyword"}
    assert fused[0]["fused_score"] > fused[1]["fused_score"]


def test_select_diverse_results_dedupes_and_caps_video_first_pass():
    video_a = uuid.uuid4()
    video_b = uuid.uuid4()
    video_c = uuid.uuid4()
    candidates = [
        _candidate(uuid.uuid4(), video_a, "same text"),
        _candidate(uuid.uuid4(), video_a, "second text"),
        _candidate(uuid.uuid4(), video_b, "same text"),
        _candidate(uuid.uuid4(), video_b, "third text"),
        _candidate(uuid.uuid4(), video_c, "fourth text"),
    ]

    selected = select_diverse_results(candidates, limit=3, per_video_limit=1)

    assert len(selected) == 3
    assert [item["video_id"] for item in selected] == [
        str(video_a),
        str(video_b),
        str(video_c),
    ]


def test_balance_source_types_includes_transcripts_when_available():
    summary_video = uuid.uuid4()
    transcript_video = uuid.uuid4()
    selected = [
        _candidate(uuid.uuid4(), summary_video, f"summary {idx}", score=0.05 - idx / 100, source_type="summary")
        for idx in range(6)
    ]
    candidates = selected + [
        _candidate(uuid.uuid4(), transcript_video, "transcript one", score=0.025, source_type="transcript"),
        _candidate(uuid.uuid4(), transcript_video, "transcript two", score=0.024, source_type="transcript"),
    ]

    balanced = balance_source_types(selected, candidates, limit=6)

    assert len(balanced) == 6
    assert sum(1 for item in balanced if item["source_type"] == "transcript") >= 1


def test_balance_source_types_leaves_summary_only_results_alone():
    selected = [
        _candidate(uuid.uuid4(), uuid.uuid4(), f"summary {idx}", source_type="summary")
        for idx in range(3)
    ]

    assert balance_source_types(selected, selected, limit=3) == selected


def test_build_evidence_text_prefers_matching_sentences():
    text = (
        "This intro sentence is unrelated. "
        "The deployment plan uses staged rollouts and rollback checks. "
        "Another unrelated detail follows. "
        "Deployment also needs queue health monitoring. "
    ) * 8

    evidence = build_evidence_text("deployment rollback", text, max_chars=180)

    assert "deployment plan" in evidence.lower()
    assert evidence.endswith("...")
    assert len(evidence) <= 183


def test_build_youtube_url_handles_missing_and_timestamp():
    assert build_youtube_url(None, 12) is None
    assert build_youtube_url("vid", None) == "https://www.youtube.com/watch?v=vid"
    assert build_youtube_url("vid", 5.9) == "https://www.youtube.com/watch?v=vid&t=5s"
