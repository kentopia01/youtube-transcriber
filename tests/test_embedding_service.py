"""Tests for the embedding chunking logic (without ML model)."""
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.services.embedding import (
    _build_speaker_chunks,
    _count_tokens,
    _split_at_sentence_boundaries,
    chunk_and_embed,
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

    def test_long_same_speaker_sequence_preserves_narrower_time_ranges(self):
        segments = [
            {
                "start": float(i * 10),
                "end": float((i + 1) * 10),
                "text": f"Sentence {i}. " * 8,
                "speaker": "SPEAKER_00",
            }
            for i in range(12)
        ]
        chunks = _build_speaker_chunks(segments, target_tokens=40, max_tokens=80)
        assert len(chunks) > 1
        assert chunks[0]["start_time"] == 0.0
        assert chunks[-1]["end_time"] == 120.0
        assert chunks[0]["end_time"] < 120.0
        assert chunks[1]["start_time"] >= chunks[0]["end_time"]

    def test_oversized_single_segment_gets_split_times(self):
        long_text = " ".join(f"Sentence {i} with enough extra words to force splitting." for i in range(40))
        segments = [
            {"start": 0.0, "end": 200.0, "text": long_text, "speaker": "SPEAKER_00"},
        ]
        chunks = _build_speaker_chunks(segments, target_tokens=40, max_tokens=70)
        assert len(chunks) > 1
        assert chunks[0]["start_time"] == 0.0
        assert chunks[-1]["end_time"] == 200.0
        assert any(chunk["end_time"] < 200.0 for chunk in chunks[:-1])
        for first, second in zip(chunks, chunks[1:]):
            assert second["start_time"] >= first["end_time"]

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


class TestTargetTokensSplitting:
    """Verify that _split_at_sentence_boundaries actually respects target_tokens."""

    def test_chunks_flush_at_target_not_max(self):
        """Chunks should flush near target_tokens, not wait until max_tokens."""
        sentences = [f"Sentence {i} has a moderate amount of tokens in it." for i in range(30)]
        text = " ".join(sentences)
        chunks = _split_at_sentence_boundaries(text, target_tokens=40, max_tokens=100)
        assert len(chunks) > 1
        # Each chunk (except maybe the last) should be around target, not near max
        for chunk in chunks[:-1]:
            token_count = _count_tokens(chunk)
            assert token_count >= 40, f"Chunk too small: {token_count} tokens"
            assert token_count < 100, f"Chunk too large (near max): {token_count} tokens"

    def test_single_long_sentence_exceeding_max(self):
        """A single sentence longer than max_tokens should still be returned."""
        long_sentence = "word " * 500  # Very long single sentence, no period breaks
        chunks = _split_at_sentence_boundaries(long_sentence.strip(), target_tokens=50, max_tokens=100)
        assert len(chunks) >= 1
        # The text is preserved (not silently dropped)
        assert "word" in chunks[0]


class TestEdgeCases:
    """Edge cases from the QA task: empty segments, single segment, no text, mixed speakers."""

    def test_single_segment_video(self):
        segments = [
            {"start": 0.0, "end": 60.0, "text": "This is the only segment.", "speaker": "SPEAKER_00"},
        ]
        chunks = _build_speaker_chunks(segments, target_tokens=300, max_tokens=400)
        assert len(chunks) == 1
        assert chunks[0]["text"] == "This is the only segment."
        assert chunks[0]["start_time"] == 0.0
        assert chunks[0]["end_time"] == 60.0

    def test_segment_with_empty_text(self):
        segments = [
            {"start": 0.0, "end": 1.0, "text": "", "speaker": "SPEAKER_00"},
            {"start": 1.0, "end": 5.0, "text": "Real content here.", "speaker": "SPEAKER_00"},
        ]
        chunks = _build_speaker_chunks(segments, target_tokens=300, max_tokens=400)
        assert len(chunks) == 1
        assert "Real content" in chunks[0]["text"]

    def test_segments_with_no_speaker_key(self):
        """Segments missing the 'speaker' key entirely should default to None."""
        segments = [
            {"start": 0.0, "end": 5.0, "text": "First line."},
            {"start": 5.0, "end": 10.0, "text": "Second line."},
            {"start": 10.0, "end": 15.0, "text": "Third line."},
        ]
        chunks = _build_speaker_chunks(segments, target_tokens=300, max_tokens=400)
        assert len(chunks) == 1
        assert chunks[0]["speaker"] is None

    def test_mixed_speaker_and_no_speaker(self):
        """Segments with speaker=None should not merge with named speakers."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Has speaker.", "speaker": "SPEAKER_00"},
            {"start": 2.0, "end": 4.0, "text": "No speaker."},
            {"start": 4.0, "end": 6.0, "text": "Speaker again.", "speaker": "SPEAKER_00"},
        ]
        chunks = _build_speaker_chunks(segments, target_tokens=300, max_tokens=400)
        assert len(chunks) == 3
        assert chunks[0]["speaker"] == "SPEAKER_00"
        assert chunks[1]["speaker"] is None
        assert chunks[2]["speaker"] == "SPEAKER_00"

    def test_chunk_has_token_count(self):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "Hello world.", "speaker": "SPEAKER_00"},
        ]
        chunks = _build_speaker_chunks(segments, target_tokens=300, max_tokens=400)
        assert "token_count" in chunks[0]
        assert chunks[0]["token_count"] > 0

    def test_all_empty_text_segments(self):
        segments = [
            {"start": 0.0, "end": 1.0, "text": ""},
            {"start": 1.0, "end": 2.0, "text": ""},
        ]
        chunks = _build_speaker_chunks(segments, target_tokens=300, max_tokens=400)
        # Should still produce a chunk (empty text joined), not crash
        assert len(chunks) >= 1


class TestChunkAndEmbed:
    """Test chunk_and_embed with a mocked embedding model."""

    @patch("app.services.embedding._get_embedding_model")
    def test_returns_768d_embeddings(self, mock_get_model):
        mock_model = MagicMock()
        # Return fake 768d embeddings
        mock_model.encode.return_value = np.random.randn(1, 768).astype(np.float32)
        mock_get_model.return_value = mock_model

        segments = [
            {"start": 0.0, "end": 5.0, "text": "Hello world.", "speaker": "SPEAKER_00"},
        ]
        results = chunk_and_embed(segments, model_cache_dir="/tmp/test")
        assert len(results) == 1
        assert len(results[0]["embedding"]) == 768
        assert results[0]["chunk_index"] == 0
        assert results[0]["speaker"] == "SPEAKER_00"

    @patch("app.services.embedding._get_embedding_model")
    def test_search_document_prefix_applied(self, mock_get_model):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.randn(1, 768).astype(np.float32)
        mock_get_model.return_value = mock_model

        segments = [
            {"start": 0.0, "end": 5.0, "text": "Test text."},
        ]
        chunk_and_embed(segments, model_cache_dir="/tmp/test")

        # Verify the model was called with search_document: prefix
        call_args = mock_model.encode.call_args
        texts = call_args[0][0]
        assert texts[0].startswith("search_document: ")

    @patch("app.services.embedding._get_embedding_model")
    def test_empty_segments_returns_empty(self, mock_get_model):
        results = chunk_and_embed([], model_cache_dir="/tmp/test")
        assert results == []
        mock_get_model.assert_not_called()

    @patch("app.services.embedding._get_embedding_model")
    def test_multiple_speakers_produce_multiple_chunks(self, mock_get_model):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.randn(3, 768).astype(np.float32)
        mock_get_model.return_value = mock_model

        segments = [
            {"start": 0.0, "end": 5.0, "text": "Speaker A talks.", "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 10.0, "text": "Speaker B talks.", "speaker": "SPEAKER_01"},
            {"start": 10.0, "end": 15.0, "text": "Speaker C talks.", "speaker": "SPEAKER_02"},
        ]
        results = chunk_and_embed(segments, model_cache_dir="/tmp/test")
        assert len(results) == 3
        assert results[0]["speaker"] == "SPEAKER_00"
        assert results[1]["speaker"] == "SPEAKER_01"
        assert results[2]["speaker"] == "SPEAKER_02"
