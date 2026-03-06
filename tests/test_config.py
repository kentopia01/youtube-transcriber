"""Tests for configuration defaults and engine selection."""

import os

import pytest

from app.config import Settings


class TestConfigDefaults:
    """Test that all V2 config vars have correct defaults."""

    def test_worker_mode_default(self):
        s = Settings(database_url="x", database_url_sync="x", redis_url="x")
        assert s.worker_mode == "docker"

    def test_transcription_engine_default(self):
        s = Settings(database_url="x", database_url_sync="x", redis_url="x")
        assert s.transcription_engine == "faster-whisper"

    def test_whisper_model_default(self):
        s = Settings(database_url="x", database_url_sync="x", redis_url="x")
        assert s.whisper_model == "mlx-community/whisper-large-v3-turbo"

    def test_whisper_detect_model_default(self):
        s = Settings(database_url="x", database_url_sync="x", redis_url="x")
        assert s.whisper_detect_model == "mlx-community/whisper-tiny"

    def test_whisper_language_default(self):
        s = Settings(database_url="x", database_url_sync="x", redis_url="x")
        assert s.whisper_language == "auto"

    def test_diarization_disabled_by_default(self):
        s = Settings(database_url="x", database_url_sync="x", redis_url="x")
        assert s.diarization_enabled is False

    def test_transcript_cleanup_disabled_by_default(self):
        s = Settings(database_url="x", database_url_sync="x", redis_url="x")
        assert s.transcript_cleanup_enabled is False

    def test_cleanup_model_default(self):
        s = Settings(database_url="x", database_url_sync="x", redis_url="x")
        assert s.cleanup_model == "claude-haiku-4-20250514"

    def test_hf_token_default_empty(self, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        s = Settings(database_url="x", database_url_sync="x", redis_url="x", _env_file=None)
        assert s.hf_token == ""

    def test_anthropic_api_key_default_empty(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        s = Settings(database_url="x", database_url_sync="x", redis_url="x", _env_file=None)
        assert s.anthropic_api_key == ""

    def test_whisper_model_size_default(self):
        s = Settings(database_url="x", database_url_sync="x", redis_url="x")
        assert s.whisper_model_size == "base"

    def test_whisper_device_default(self):
        s = Settings(database_url="x", database_url_sync="x", redis_url="x")
        assert s.whisper_device == "cpu"

    def test_whisper_compute_type_default(self):
        s = Settings(database_url="x", database_url_sync="x", redis_url="x")
        assert s.whisper_compute_type == "int8"

    def test_embedding_model_default(self):
        s = Settings(database_url="x", database_url_sync="x", redis_url="x")
        assert s.embedding_model == "nomic-ai/nomic-embed-text-v1.5"

    def test_embedding_dimensions_default(self):
        s = Settings(database_url="x", database_url_sync="x", redis_url="x")
        assert s.embedding_dimensions == 768

    def test_chunk_target_tokens_default(self):
        s = Settings(database_url="x", database_url_sync="x", redis_url="x")
        assert s.chunk_target_tokens == 300

    def test_chunk_max_tokens_default(self):
        s = Settings(database_url="x", database_url_sync="x", redis_url="x")
        assert s.chunk_max_tokens == 400

    def test_embedding_settings_overridable(self):
        s = Settings(
            database_url="x", database_url_sync="x", redis_url="x",
            embedding_model="custom/model",
            embedding_dimensions=512,
            chunk_target_tokens=200,
            chunk_max_tokens=300,
        )
        assert s.embedding_model == "custom/model"
        assert s.embedding_dimensions == 512
        assert s.chunk_target_tokens == 200
        assert s.chunk_max_tokens == 300


class TestNativeVsDockerConfig:
    """Test configuration differences between native and Docker modes."""

    def test_native_mode_uses_mlx_engine(self):
        s = Settings(
            database_url="x", database_url_sync="x", redis_url="x",
            worker_mode="native",
            transcription_engine="mlx",
        )
        assert s.worker_mode == "native"
        assert s.transcription_engine == "mlx"

    def test_docker_mode_uses_faster_whisper(self):
        s = Settings(
            database_url="x", database_url_sync="x", redis_url="x",
            worker_mode="docker",
            transcription_engine="faster-whisper",
        )
        assert s.worker_mode == "docker"
        assert s.transcription_engine == "faster-whisper"


class TestEngineSelectionFromConfig:
    """Test that get_engine returns the right engine based on config values."""

    def test_mlx_config_creates_mlx_engine(self):
        from app.services.transcription import MLXWhisperEngine, get_engine
        engine = get_engine("mlx")
        assert isinstance(engine, MLXWhisperEngine)

    def test_faster_whisper_config_creates_faster_engine(self):
        from app.services.transcription import FasterWhisperEngine, get_engine
        engine = get_engine("faster-whisper")
        assert isinstance(engine, FasterWhisperEngine)

    def test_invalid_engine_config_raises(self):
        from app.services.transcription import get_engine
        with pytest.raises(ValueError, match="Unknown transcription engine"):
            get_engine("invalid-engine")

    def test_mlx_engine_receives_model_params(self):
        from app.services.transcription import get_engine
        engine = get_engine(
            "mlx",
            whisper_model="custom/model",
            whisper_detect_model="custom/detect",
        )
        assert engine.model == "custom/model"
        assert engine.detect_model == "custom/detect"

    def test_faster_whisper_engine_receives_params(self):
        from app.services.transcription import get_engine
        engine = get_engine(
            "faster-whisper",
            model_size="large",
            device="cuda",
            compute_type="float16",
            model_cache_dir="/custom/cache",
        )
        assert engine.model_size == "large"
        assert engine.device == "cuda"
        assert engine.compute_type == "float16"
        assert engine.model_cache_dir == "/custom/cache"
