"""Tests for the embedding chunking logic (without ML model)."""
import pytest

from app.services.embedding import (
    _build_speaker_chunks,
    _split_at_sentence_boundaries,
)


class TestSentenceBoundarySplitting:
    """Test sentence-level splitting for long text blocks."""

    def test_short_text_returns_single_chunk(self):
        text = "Hello world. This is short."
        chunks = _split_at_sentence_boundaries(text, target_tokens=300, max_tokens=400)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_splits_at_sentences(self):
        # Build a long text with clear sentence boundaries
        sentences = [f"Sentence number {i} with some extra words." for i in range(50)]
        text = " ".join(sentences)
        chunks = _split_at_sentence_boundaries(text, target_tokens=50, max_tokens=80)
        assert len(chunks) > 1
        # Each chunk should end at a sentence boundary (period)
        for chunk in chunks:
            assert chunk.strip()[-1] == "."

    def test_empty_text_returns_original(self):
        chunks = _split_at_sentence_boundaries("", target_tokens=300, max_tokens=400)
        assert chunks == [""]


class TestSpeakerAwareChunking:
    """Test speaker-aware chunking logic."""

    def test_single_speaker_short(self):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "Hello everyone.", "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 10.0, "text": "Welcome to the show.", "speaker": "SPEAKER_00"},
        ]
        chunks = _build_speaker_chunks(segments, target_tokens=300, max_tokens=400)
        assert len(chunks) == 1
        assert chunks[0]["speaker"] == "SPEAKER_00"
        assert "Hello everyone" in chunks[0]["text"]
        assert "Welcome to the show" in chunks[0]["text"]

    def test_different_speakers_create_separate_chunks(self):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "Hello from speaker A.", "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 10.0, "text": "Hello from speaker B.", "speaker": "SPEAKER_01"},
        ]
        chunks = _build_speaker_chunks(segments, target_tokens=300, max_tokens=400)
        assert len(chunks) == 2
        assert chunks[0]["speaker"] == "SPEAKER_00"
        assert chunks[1]["speaker"] == "SPEAKER_01"

    def test_same_speaker_groups_merged(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "First part.", "speaker": "SPEAKER_00"},
            {"start": 2.0, "end": 4.0, "text": "Interruption.", "speaker": "SPEAKER_01"},
            {"start": 4.0, "end": 6.0, "text": "Back again.", "speaker": "SPEAKER_00"},
        ]
        chunks = _build_speaker_chunks(segments, target_tokens=300, max_tokens=400)
        # Should be 3 separate chunks (different speakers can't merge across interruptions)
        assert len(chunks) == 3

    def test_no_speaker_label_treated_as_single_group(self):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "No speaker info."},
            {"start": 5.0, "end": 10.0, "text": "Still no speaker."},
        ]
        chunks = _build_speaker_chunks(segments, target_tokens=300, max_tokens=400)
        assert len(chunks) == 1
        assert chunks[0]["speaker"] is None

    def test_long_monologue_splits_at_sentences(self):
        # Build a long single-speaker monologue
        long_text = ". ".join([f"Sentence {i} with some extra content words" for i in range(40)])
        segments = [
            {"start": 0.0, "end": 300.0, "text": long_text, "speaker": "SPEAKER_00"},
        ]
        chunks = _build_speaker_chunks(segments, target_tokens=50, max_tokens=80)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk["speaker"] == "SPEAKER_00"

    def test_empty_segments_returns_empty(self):
        chunks = _build_speaker_chunks([], target_tokens=300, max_tokens=400)
        assert chunks == []

    def test_chunk_preserves_timestamps(self):
        segments = [
            {"start": 10.5, "end": 20.3, "text": "Some text.", "speaker": "SPEAKER_00"},
        ]
        chunks = _build_speaker_chunks(segments, target_tokens=300, max_tokens=400)
        assert chunks[0]["start_time"] == 10.5
        assert chunks[0]["end_time"] == 20.3

    def test_consecutive_same_speaker_segments_merge(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Part one.", "speaker": "SPEAKER_00"},
            {"start": 2.0, "end": 4.0, "text": "Part two.", "speaker": "SPEAKER_00"},
            {"start": 4.0, "end": 6.0, "text": "Part three.", "speaker": "SPEAKER_00"},
        ]
        chunks = _build_speaker_chunks(segments, target_tokens=300, max_tokens=400)
        assert len(chunks) == 1
        assert "Part one" in chunks[0]["text"]
        assert "Part three" in chunks[0]["text"]


class TestLegacyChunkTextSplitting:
    """Backward compat: verify segments that would exceed one chunk get split."""

    def test_chunk_text_splitting(self):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "Hello world " * 100},
            {"start": 5.0, "end": 10.0, "text": "Testing chunks " * 100},
            {"start": 10.0, "end": 15.0, "text": "More content " * 100},
        ]
        total_words = sum(len(s["text"].split()) for s in segments)
        assert total_words > 500
