from types import SimpleNamespace

from app.services.diarization_decision import (
    DECISION_DEFER,
    DECISION_REVIEW,
    DECISION_SKIP,
    PROFILE_LIKELY_MULTI,
    PROFILE_LIKELY_SOLO,
    PROFILE_UNCERTAIN,
    VALUE_HIGH,
    VALUE_LOW,
    decide_diarization_usefulness,
)
from app.tasks.transcribe import _record_diarization_decision


def test_podcast_guest_format_defers_diarization():
    decision = decide_diarization_usefulness(
        title="Live interview with Dex Horthy",
        channel_name="AI Builders Podcast",
        transcript_text=(
            "Welcome back to the show. Today my guest is Dex. "
            "Thanks for having me. Let me ask you how you think about coding agents?"
        ),
    )

    assert decision.decision == DECISION_DEFER
    assert decision.speaker_profile == PROFILE_LIKELY_MULTI
    assert decision.speaker_labels_value == VALUE_HIGH
    assert decision.confidence >= 0.7
    assert "transcript sample contains conversation cues" in decision.reasons


def test_solo_coding_tutorial_skips_diarization():
    decision = decide_diarization_usefulness(
        title="Build a tokenizer from scratch - coding tutorial",
        channel_name="Engineering Notes",
        segment_texts=[
            "In this video I want to show how tokenizers work.",
            "Let's build the parser step by step.",
            "I'll show you the implementation details now.",
        ],
    )

    assert decision.decision == DECISION_SKIP
    assert decision.speaker_profile == PROFILE_LIKELY_SOLO
    assert decision.speaker_labels_value == VALUE_LOW
    assert decision.confidence >= 0.7


def test_uncertain_video_goes_to_review_without_forcing_diarization():
    decision = decide_diarization_usefulness(
        title="New AI systems in production",
        channel_name="Tech Updates",
        transcript_text="This covers several deployments and their operational details.",
    )

    assert decision.decision == DECISION_REVIEW
    assert decision.speaker_profile == PROFILE_UNCERTAIN


def test_transcript_conversation_cues_override_solo_title_signal():
    decision = decide_diarization_usefulness(
        title="AI coding demo explained",
        channel_name="Founder Notes",
        transcript_text=(
            "Welcome to the show. My guest today has been building developer tools. "
            "Thanks for having me. Let me ask you what do you think about agents?"
        ),
    )

    assert decision.decision == DECISION_DEFER
    assert decision.speaker_profile == PROFILE_LIKELY_MULTI


def test_record_diarization_decision_persists_bounded_structured_blob():
    video = SimpleNamespace(
        title="Panel: AI agents in engineering",
        description="A panel discussion with founders and operators.",
        channel=SimpleNamespace(name="Operator Podcast"),
    )
    job = SimpleNamespace(last_artifact_check_result={"transcription": {"exists": True}})
    result = {
        "text": "Welcome to the show. My guest is here. Thanks for having me.",
        "segments": [
            {"text": "Welcome to the show."},
            {"text": "My guest is here."},
            {"text": "Thanks for having me."},
        ],
    }

    decision = _record_diarization_decision(video, result, job=job)

    assert decision.decision == DECISION_DEFER
    assert job.last_artifact_check_result["transcription"] == {"exists": True}
    persisted = job.last_artifact_check_result["diarization_decision"]
    assert persisted["schema_version"] == 1
    assert persisted["detector"] == "heuristic_v1"
    assert persisted["decision"] == DECISION_DEFER
    assert "text" not in persisted
    assert job.last_artifact_check_result["diarization_decision_at"] is not None
