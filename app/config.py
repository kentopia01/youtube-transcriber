from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://transcriber:transcriber@postgres:5432/transcriber"
    database_url_sync: str = "postgresql+psycopg2://transcriber:transcriber@postgres:5432/transcriber"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Claude API
    anthropic_api_key: str = ""

    # Worker mode: "native" (macOS Metal) or "docker" (CPU via faster-whisper)
    worker_mode: str = "docker"

    # Transcription engine: "mlx" (Apple Silicon) or "faster-whisper" (CPU)
    transcription_engine: str = "faster-whisper"

    # Whisper — legacy (faster-whisper / Docker)
    whisper_model_size: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # Whisper — MLX models (native macOS)
    whisper_model: str = "mlx-community/whisper-large-v3-turbo"
    whisper_detect_model: str = "mlx-community/whisper-tiny"
    whisper_language: str = "auto"

    # HuggingFace (for pyannote diarization)
    hf_token: str = ""

    # Pipeline toggles
    diarization_enabled: bool = False
    transcript_cleanup_enabled: bool = False

    # LLM cleanup
    cleanup_model: str = "claude-haiku-4-20250514"

    # LLM summarization
    summary_model: str = "claude-haiku-4-20250514"

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    audio_dir: str = "/data/audio"
    model_cache_dir: str = "/data/models"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
