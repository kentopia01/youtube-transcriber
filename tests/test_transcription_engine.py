"""Tests for the pluggable transcription engine system."""

from unittest.mock import MagicMock, patch

import pytest

from app.services import transcription as transcription_module
from app.services.transcription import (
    FasterWhisperEngine,
    MLXWhisperEngine,
    TranscriptResult,
    get_engine,
    transcribe_audio,
)


@pytest.fixture(autouse=True)
def _reset_engine_cache():
    transcription_module._reset_caches()
    yield
    transcription_module._reset_caches()


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

    def test_faster_whisper_engine_cached_on_same_args(self):
        a = get_engine("faster-whisper", model_size="base", device="cpu", compute_type="int8")
        b = get_engine("faster-whisper", model_size="base", device="cpu", compute_type="int8")
        assert a is b

    def test_faster_whisper_engine_new_instance_on_diff_args(self):
        a = get_engine("faster-whisper", model_size="base", device="cpu", compute_type="int8")
        b = get_engine("faster-whisper", model_size="small", device="cpu", compute_type="int8")
        assert a is not b

    def test_mlx_engine_cached_on_same_args(self):
        a = get_engine("mlx", whisper_model="mlx-community/whisper-large-v3-turbo")
        b = get_engine("mlx", whisper_model="mlx-community/whisper-large-v3-turbo")
        assert a is b

    def test_mlx_engine_new_instance_on_diff_model(self):
        a = get_engine("mlx", whisper_model="mlx-community/whisper-large-v3-turbo")
        b = get_engine("mlx", whisper_model="mlx-community/whisper-tiny")
        assert a is not b


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


class TestLanguageDetection:
    """Tests for language detection flow (Phase 1)."""

    @patch("app.services.transcription.get_engine")
    def test_mlx_auto_language_calls_detect(self, mock_get_engine):
        """When engine=mlx and language=auto, detect_language is called."""
        mock_engine = MagicMock()
        mock_engine.detect_language.return_value = "ja"
        mock_engine.transcribe.return_value = TranscriptResult(
            text="こんにちは世界", language="ja", segments=[], processing_time=1.0
        )
        mock_get_engine.return_value = mock_engine

        result = transcribe_audio(
            "/fake/audio.wav",
            engine_type="mlx",
            whisper_language="auto",
        )

        mock_engine.detect_language.assert_called_once_with("/fake/audio.wav")
        mock_engine.transcribe.assert_called_once_with("/fake/audio.wav", language="ja")
        assert result["language"] == "ja"

    @patch("app.services.transcription.get_engine")
    def test_mlx_forced_language_skips_detect(self, mock_get_engine):
        """When language is forced (not auto), detect_language is NOT called."""
        mock_engine = MagicMock()
        mock_engine.transcribe.return_value = TranscriptResult(
            text="hello world", language="en", segments=[], processing_time=0.5
        )
        mock_get_engine.return_value = mock_engine

        result = transcribe_audio(
            "/fake/audio.wav",
            engine_type="mlx",
            whisper_language="en",
        )

        mock_engine.detect_language.assert_not_called()
        mock_engine.transcribe.assert_called_once_with("/fake/audio.wav", language="en")
        assert result["language"] == "en"

    @patch("app.services.transcription.get_engine")
    def test_faster_whisper_skips_detect(self, mock_get_engine):
        """Faster-whisper engine does not call detect_language (Whisper handles it)."""
        mock_engine = MagicMock()
        mock_engine.transcribe.return_value = TranscriptResult(
            text="hello world", language="en", segments=[], processing_time=0.5
        )
        mock_get_engine.return_value = mock_engine

        result = transcribe_audio(
            "/fake/audio.wav",
            engine_type="faster-whisper",
            whisper_language="auto",
        )

        mock_engine.detect_language.assert_not_called()
        mock_engine.transcribe.assert_called_once_with("/fake/audio.wav", language=None)
        assert result["language"] == "en"
