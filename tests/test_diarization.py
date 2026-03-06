"""Tests for speaker diarization and alignment services."""

import pytest

from app.services.alignment import _find_speaker, align_and_merge


class TestFindSpeaker:
    """Test the majority-vote speaker assignment."""

    def test_single_speaker_full_overlap(self):
        diar = [{"start": 0.0, "end": 10.0, "speaker": "SPEAKER_00"}]
        assert _find_speaker(0.0, 5.0, diar) == "SPEAKER_00"

    def test_multiple_speakers_majority_wins(self):
        diar = [
            {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00"},
            {"start": 3.0, "end": 10.0, "speaker": "SPEAKER_01"},
        ]
        # Segment 2.0-8.0: SPEAKER_00 covers 1.0s, SPEAKER_01 covers 5.0s
        assert _find_speaker(2.0, 8.0, diar) == "SPEAKER_01"

    def test_no_overlap_returns_none(self):
        diar = [{"start": 10.0, "end": 20.0, "speaker": "SPEAKER_00"}]
        assert _find_speaker(0.0, 5.0, diar) is None

    def test_exact_boundary(self):
        diar = [
            {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 10.0, "speaker": "SPEAKER_01"},
        ]
        # Exactly at boundary — no overlap with SPEAKER_00
        assert _find_speaker(5.0, 8.0, diar) == "SPEAKER_01"

    def test_equal_overlap_picks_one(self):
        diar = [
            {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 10.0, "speaker": "SPEAKER_01"},
        ]
        # 3.0-7.0: both have 2.0s overlap
        result = _find_speaker(3.0, 7.0, diar)
        assert result in ("SPEAKER_00", "SPEAKER_01")

    def test_empty_diarization(self):
        assert _find_speaker(0.0, 5.0, []) is None


class TestAlignAndMerge:
    """Test alignment and speaker merge (without whisperX)."""

    def test_no_diarization_returns_none_speakers(self):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "hello", "confidence": -0.5},
        ]
        result = align_and_merge("/fake.wav", segments, [], "en")
        assert len(result) == 1
        assert result[0]["speaker"] is None
        assert result[0]["text"] == "hello"

    def test_basic_speaker_assignment(self):
        segments = [
            {"start": 0.0, "end": 3.0, "text": "Hello everyone", "confidence": -0.3},
            {"start": 3.5, "end": 7.0, "text": "Thanks for having me", "confidence": -0.4},
        ]
        diar = [
            {"start": 0.0, "end": 3.5, "speaker": "SPEAKER_00"},
            {"start": 3.5, "end": 8.0, "speaker": "SPEAKER_01"},
        ]
        result = align_and_merge("/fake.wav", segments, diar, "en")
        assert len(result) == 2
        assert result[0]["speaker"] == "SPEAKER_00"
        assert result[1]["speaker"] == "SPEAKER_01"

    def test_preserves_original_fields(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "test", "confidence": -0.2},
        ]
        diar = [{"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"}]
        result = align_and_merge("/fake.wav", segments, diar, "en")
        assert result[0]["text"] == "test"
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 2.0
