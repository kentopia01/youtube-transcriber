"""Tests for the LLM transcript cleanup service."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.transcript_cleanup import (
    _build_chunks,
    _map_cleaned_to_segments,
    clean_transcript,
)


class TestBuildChunks:
    """Test token-aware chunking."""

    def _get_enc(self):
        import tiktoken
        return tiktoken.get_encoding("cl100k_base")

    def test_single_chunk_for_short_text(self):
        enc = self._get_enc()
        lines = ["Hello world", "How are you"]
        chunks = _build_chunks(lines, enc)
        assert len(chunks) == 1
        assert chunks[0] == lines

    def test_splits_long_text(self):
        enc = self._get_enc()
        # Create lines that exceed CHUNK_SIZE (2000 tokens)
        lines = [f"This is a fairly long sentence number {i} that we use for testing." for i in range(200)]
        chunks = _build_chunks(lines, enc)
        assert len(chunks) > 1

    def test_empty_input(self):
        enc = self._get_enc()
        chunks = _build_chunks([], enc)
        assert chunks == []


class TestMapCleanedToSegments:
    """Test mapping cleaned text back to segments."""

    def test_basic_mapping(self):
        cleaned = "Hello world\nGoodbye world"
        segments = [
            {"text": "Hello um world", "speaker": None, "start": 0.0},
            {"text": "Goodbye uh world", "speaker": None, "start": 5.0},
        ]
        result = _map_cleaned_to_segments(cleaned, segments)
        assert result[0]["text"] == "Hello world"
        assert result[1]["text"] == "Goodbye world"
        assert result[0]["start"] == 0.0  # preserved

    def test_strips_speaker_labels(self):
        cleaned = "[SPEAKER_00] Hello there\n[SPEAKER_01] Hi"
        segments = [
            {"text": "um Hello there", "speaker": "SPEAKER_00"},
            {"text": "uh Hi", "speaker": "SPEAKER_01"},
        ]
        result = _map_cleaned_to_segments(cleaned, segments)
        assert result[0]["text"] == "Hello there"
        assert result[1]["text"] == "Hi"

    def test_preserves_metadata(self):
        cleaned = "Clean text"
        segments = [
            {"text": "Original", "speaker": "SPEAKER_00", "start": 1.5, "end": 3.0, "confidence": -0.3},
        ]
        result = _map_cleaned_to_segments(cleaned, segments)
        assert result[0]["text"] == "Clean text"
        assert result[0]["start"] == 1.5
        assert result[0]["end"] == 3.0
        assert result[0]["confidence"] == -0.3

    def test_handles_fewer_cleaned_lines(self):
        """If LLM returns fewer lines than segments, keep original for extras."""
        cleaned = "Only one line"
        segments = [
            {"text": "First", "speaker": None},
            {"text": "Second", "speaker": None},
        ]
        result = _map_cleaned_to_segments(cleaned, segments)
        assert result[0]["text"] == "Only one line"
        assert result[1]["text"] == "Second"  # kept original


class TestCleanTranscript:
    """Test the main clean_transcript function."""

    def test_empty_segments(self):
        result = clean_transcript([], api_key="key", model="test")
        assert result == []

    def test_no_api_key_returns_original(self):
        segments = [{"text": "hello um world", "speaker": None}]
        result = clean_transcript(segments, api_key="", model="test")
        assert result == segments

    @patch("app.services.transcript_cleanup._call_llm")
    def test_calls_llm_with_text(self, mock_llm):
        mock_llm.return_value = "Hello world"
        segments = [{"text": "Hello um world", "speaker": None}]
        result = clean_transcript(segments, api_key="test-key", model="test-model")
        mock_llm.assert_called_once()
        assert result[0]["text"] == "Hello world"

    @patch("app.services.transcript_cleanup._call_llm")
    def test_speaker_labels_in_llm_input(self, mock_llm):
        mock_llm.return_value = "[SPEAKER_00] Hello there"
        segments = [{"text": "um Hello there", "speaker": "SPEAKER_00"}]
        result = clean_transcript(segments, api_key="test-key", model="test-model")
        # Check the LLM was called with speaker-labeled text
        call_text = mock_llm.call_args[0][0]
        assert "[SPEAKER_00]" in call_text
        # Result should have the label stripped
        assert result[0]["text"] == "Hello there"
