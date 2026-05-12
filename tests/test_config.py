"""Tests for configuration defaults and engine selection."""

import os

import pytest

from app.config import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_CLEANUP_MODEL,
    DEFAULT_DIGEST_MODEL,
    DEFAULT_PERSONA_MODEL,
    DEFAULT_SUMMARY_MODEL,
    Settings,
)


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
        assert s.cleanup_model == DEFAULT_CLEANUP_MODEL

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


class TestCanonicalModelSettings:
    """Config contract for canonical LLM model settings and deprecated aliases."""

    MODEL_ENV_VARS = (
        "CLEANUP_MODEL",
        "SUMMARY_MODEL",
        "CHAT_MODEL",
        "PERSONA_MODEL",
        "DIGEST_MODEL",
        "ANTHROPIC_CLEANUP_MODEL",
        "ANTHROPIC_SUMMARY_MODEL",
        "ANTHROPIC_CHAT_MODEL",
        "ANTHROPIC_PERSONA_MODEL",
    )

    def _clear_model_env(self, monkeypatch):
        for name in self.MODEL_ENV_VARS:
            monkeypatch.delenv(name, raising=False)

    def _settings(self):
        return Settings(database_url="x", database_url_sync="x", redis_url="x", _env_file=None)

    def test_model_defaults_are_canonical_per_use_case(self, monkeypatch):
        self._clear_model_env(monkeypatch)

        s = self._settings()

        assert s.cleanup_model == DEFAULT_CLEANUP_MODEL
        assert s.summary_model == DEFAULT_SUMMARY_MODEL
        assert s.chat_model == DEFAULT_CHAT_MODEL
        assert s.persona_model == DEFAULT_PERSONA_MODEL
        assert s.digest_model == DEFAULT_DIGEST_MODEL
        assert s.anthropic_cleanup_model == DEFAULT_CLEANUP_MODEL
        assert s.anthropic_summary_model == DEFAULT_SUMMARY_MODEL
        assert s.anthropic_chat_model == DEFAULT_CHAT_MODEL
        assert s.anthropic_persona_model == DEFAULT_PERSONA_MODEL

    def test_canonical_model_env_vars_override_defaults(self, monkeypatch):
        self._clear_model_env(monkeypatch)
        monkeypatch.setenv("CLEANUP_MODEL", "cleanup-canonical")
        monkeypatch.setenv("SUMMARY_MODEL", "summary-canonical")
        monkeypatch.setenv("CHAT_MODEL", "chat-canonical")
        monkeypatch.setenv("PERSONA_MODEL", "persona-canonical")
        monkeypatch.setenv("DIGEST_MODEL", "digest-canonical")

        s = self._settings()

        assert s.cleanup_model == "cleanup-canonical"
        assert s.summary_model == "summary-canonical"
        assert s.chat_model == "chat-canonical"
        assert s.persona_model == "persona-canonical"
        assert s.digest_model == "digest-canonical"

    def test_deprecated_anthropic_model_env_aliases_remain_supported(self, monkeypatch):
        self._clear_model_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_CLEANUP_MODEL", "cleanup-legacy")
        monkeypatch.setenv("ANTHROPIC_SUMMARY_MODEL", "summary-legacy")
        monkeypatch.setenv("ANTHROPIC_CHAT_MODEL", "chat-legacy")
        monkeypatch.setenv("ANTHROPIC_PERSONA_MODEL", "persona-legacy")

        s = self._settings()

        assert s.cleanup_model == "cleanup-legacy"
        assert s.summary_model == "summary-legacy"
        assert s.digest_model == "summary-legacy"
        assert s.chat_model == "chat-legacy"
        assert s.persona_model == "persona-legacy"

    def test_canonical_model_env_vars_win_over_deprecated_aliases(self, monkeypatch):
        self._clear_model_env(monkeypatch)
        monkeypatch.setenv("SUMMARY_MODEL", "summary-canonical")
        monkeypatch.setenv("DIGEST_MODEL", "digest-canonical")
        monkeypatch.setenv("ANTHROPIC_SUMMARY_MODEL", "summary-legacy")

        s = self._settings()

        assert s.summary_model == "summary-canonical"
        assert s.digest_model == "digest-canonical"

    def test_deprecated_compatibility_properties_are_mutable_aliases(self, monkeypatch):
        self._clear_model_env(monkeypatch)
        s = self._settings()

        s.anthropic_cleanup_model = "cleanup-setter"
        s.anthropic_summary_model = "summary-setter"
        s.anthropic_chat_model = "chat-setter"
        s.anthropic_persona_model = "persona-setter"

        assert s.cleanup_model == "cleanup-setter"
        assert s.summary_model == "summary-setter"
        assert s.chat_model == "chat-setter"
        assert s.persona_model == "persona-setter"


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
