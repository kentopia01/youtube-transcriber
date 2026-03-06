"""Tests for the alignment service — align_and_merge() and helpers."""

from unittest.mock import patch

import pytest

from app.services.alignment import _find_speaker, align_and_merge


class TestFindSpeakerExtended:
    """Extended tests for _find_speaker majority-vote logic."""

    def test_three_speakers_overlap(self):
        diar = [
            {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
            {"start": 2.0, "end": 6.0, "speaker": "SPEAKER_01"},
            {"start": 6.0, "end": 10.0, "speaker": "SPEAKER_02"},
        ]
        # 1.0-7.0: S00=1s, S01=4s, S02=1s → S01 wins
        assert _find_speaker(1.0, 7.0, diar) == "SPEAKER_01"

    def test_tiny_overlap(self):
        diar = [{"start": 0.0, "end": 0.01, "speaker": "SPEAKER_00"}]
        assert _find_speaker(0.0, 0.01, diar) == "SPEAKER_00"

    def test_segment_after_all_diarization(self):
        diar = [{"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"}]
        assert _find_speaker(10.0, 15.0, diar) is None

    def test_segment_before_all_diarization(self):
        diar = [{"start": 10.0, "end": 15.0, "speaker": "SPEAKER_00"}]
        assert _find_speaker(0.0, 5.0, diar) is None

    def test_single_point_no_overlap(self):
        """Zero-length segment should return None."""
        diar = [{"start": 0.0, "end": 10.0, "speaker": "SPEAKER_00"}]
        assert _find_speaker(5.0, 5.0, diar) is None

    def test_gap_between_speakers(self):
        """Segment falls in a silence gap between speakers."""
        diar = [
            {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00"},
            {"start": 7.0, "end": 10.0, "speaker": "SPEAKER_01"},
        ]
        assert _find_speaker(4.0, 6.0, diar) is None

    def test_overlapping_diarization_segments(self):
        """When diarization segments themselves overlap."""
        diar = [
            {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"},
            {"start": 3.0, "end": 8.0, "speaker": "SPEAKER_01"},
        ]
        # 3.0-8.0: S00 covers 3.0-5.0=2s, S01 covers 3.0-8.0=5s → S01 wins
        assert _find_speaker(3.0, 8.0, diar) == "SPEAKER_01"


class TestAlignAndMergeExtended:
    """Extended tests for align_and_merge."""

    @patch("app.services.alignment._try_whisperx_alignment")
    def test_no_diarization_segments_adds_none_speaker(self, mock_align):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "hello", "confidence": -0.5},
            {"start": 5.0, "end": 10.0, "text": "world", "confidence": -0.3},
        ]
        result = align_and_merge("/fake.wav", segments, [], "en")
        # Should NOT call whisperX when diarization is empty
        mock_align.assert_not_called()
        assert all(s["speaker"] is None for s in result)

    @patch("app.services.alignment._try_whisperx_alignment")
    def test_single_speaker_assigns_all(self, mock_align):
        segments = [
            {"start": 0.0, "end": 3.0, "text": "first", "confidence": -0.3},
            {"start": 3.0, "end": 6.0, "text": "second", "confidence": -0.4},
            {"start": 6.0, "end": 9.0, "text": "third", "confidence": -0.2},
        ]
        diar = [{"start": 0.0, "end": 10.0, "speaker": "SPEAKER_00"}]
        # Mock whisperX to return segments unchanged
        mock_align.return_value = segments

        result = align_and_merge("/fake.wav", segments, diar, "en")
        assert all(s["speaker"] == "SPEAKER_00" for s in result)

    @patch("app.services.alignment._try_whisperx_alignment")
    def test_no_matching_speaker_for_segment(self, mock_align):
        """Transcript segment falls in a gap — no speaker match."""
        segments = [
            {"start": 5.0, "end": 7.0, "text": "in the gap", "confidence": -0.5},
        ]
        diar = [
            {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00"},
            {"start": 10.0, "end": 15.0, "speaker": "SPEAKER_01"},
        ]
        mock_align.return_value = segments

        result = align_and_merge("/fake.wav", segments, diar, "en")
        assert result[0]["speaker"] is None
        assert result[0]["text"] == "in the gap"

    @patch("app.services.alignment._try_whisperx_alignment")
    def test_multiple_segments_multiple_speakers(self, mock_align):
        """Full conversation with alternating speakers."""
        segments = [
            {"start": 0.0, "end": 4.0, "text": "Hello everyone", "confidence": -0.3},
            {"start": 4.0, "end": 8.0, "text": "Thanks for joining", "confidence": -0.4},
            {"start": 8.0, "end": 12.0, "text": "Let me start", "confidence": -0.2},
            {"start": 12.0, "end": 16.0, "text": "Sure go ahead", "confidence": -0.3},
        ]
        diar = [
            {"start": 0.0, "end": 4.5, "speaker": "SPEAKER_00"},
            {"start": 4.5, "end": 8.5, "speaker": "SPEAKER_01"},
            {"start": 8.5, "end": 12.5, "speaker": "SPEAKER_00"},
            {"start": 12.5, "end": 16.0, "speaker": "SPEAKER_01"},
        ]
        mock_align.return_value = segments

        result = align_and_merge("/fake.wav", segments, diar, "en")
        assert result[0]["speaker"] == "SPEAKER_00"
        assert result[1]["speaker"] == "SPEAKER_01"
        assert result[2]["speaker"] == "SPEAKER_00"
        assert result[3]["speaker"] == "SPEAKER_01"

    @patch("app.services.alignment._try_whisperx_alignment")
    def test_preserves_all_original_fields(self, mock_align):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "test", "confidence": -0.2, "extra": "data"},
        ]
        diar = [{"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"}]
        mock_align.return_value = segments

        result = align_and_merge("/fake.wav", segments, diar, "en")
        assert result[0]["extra"] == "data"
        assert result[0]["speaker"] == "SPEAKER_00"
        assert result[0]["text"] == "test"
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 2.0
        assert result[0]["confidence"] == -0.2

    @patch("app.services.alignment._try_whisperx_alignment")
    def test_empty_transcript_segments(self, mock_align):
        diar = [{"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"}]
        mock_align.return_value = []
        result = align_and_merge("/fake.wav", [], diar, "en")
        assert result == []
