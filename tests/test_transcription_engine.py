"""Tests for the pluggable transcription engine system."""

import pytest

from app.services.transcription import (
    FasterWhisperEngine,
    MLXWhisperEngine,
    TranscriptResult,
    get_engine,
)


class TestTranscriptResult:
    def test_to_dict(self):
        result = TranscriptResult(
            text="hello world",
            language="en",
            segments=[{"start": 0.0, "end": 1.0, "text": "hello world", "confidence": -0.5}],
            processing_time=1.23,
        )
        d = result.to_dict()
        assert d["text"] == "hello world"
        assert d["language"] == "en"
        assert len(d["segments"]) == 1
        assert d["processing_time"] == 1.23


class TestGetEngine:
    def test_faster_whisper_engine(self):
        engine = get_engine("faster-whisper", model_size="base", device="cpu", compute_type="int8")
        assert isinstance(engine, FasterWhisperEngine)

    def test_mlx_engine(self):
        engine = get_engine("mlx", whisper_model="mlx-community/whisper-large-v3-turbo")
        assert isinstance(engine, MLXWhisperEngine)

    def test_unknown_engine_raises(self):
        with pytest.raises(ValueError, match="Unknown transcription engine"):
            get_engine("nonexistent")


class TestMLXWhisperEngineInit:
    def test_attributes(self):
        engine = MLXWhisperEngine(
            model="mlx-community/whisper-large-v3-turbo",
            detect_model="mlx-community/whisper-tiny",
        )
        assert engine.model == "mlx-community/whisper-large-v3-turbo"
        assert engine.detect_model == "mlx-community/whisper-tiny"


class TestFasterWhisperEngineInit:
    def test_attributes(self):
        engine = FasterWhisperEngine(
            model_size="base",
            device="cpu",
            compute_type="int8",
            model_cache_dir="/data/models",
        )
        assert engine.model_size == "base"
        assert engine.device == "cpu"
        assert engine._model is None  # lazy init
