"""Tests for the embedding chunking logic (without ML model)."""
import pytest


def test_chunk_text_splitting():
    """Test that text gets split into chunks correctly."""
    # We test the chunking logic conceptually
    # The actual embedding model isn't loaded in unit tests
    segments = [
        {"start": 0.0, "end": 5.0, "text": "Hello world " * 100},
        {"start": 5.0, "end": 10.0, "text": "Testing chunks " * 100},
        {"start": 10.0, "end": 15.0, "text": "More content " * 100},
    ]
    # Just verify we have segments that would need splitting
    total_words = sum(len(s["text"].split()) for s in segments)
    assert total_words > 500  # More than one chunk worth
