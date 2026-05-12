from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_CLEANUP_MODEL = "claude-haiku-4-5"
DEFAULT_SUMMARY_MODEL = "claude-sonnet-4-5"
DEFAULT_CHAT_MODEL = "claude-haiku-4-5"
DEFAULT_PERSONA_MODEL = "claude-sonnet-4-5"
DEFAULT_DIGEST_MODEL = "claude-sonnet-4-5"


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

    # Canonical Anthropic model settings. Use these env vars for new config.
    # Deprecated ANTHROPIC_*_MODEL env vars remain supported as aliases below.
    cleanup_model: str = Field(
        DEFAULT_CLEANUP_MODEL,
        validation_alias=AliasChoices(
            "cleanup_model",
            "CLEANUP_MODEL",
            "anthropic_cleanup_model",
            "ANTHROPIC_CLEANUP_MODEL",
        ),
    )
    summary_model: str = Field(
        DEFAULT_SUMMARY_MODEL,
        validation_alias=AliasChoices(
            "summary_model",
            "SUMMARY_MODEL",
            "anthropic_summary_model",
            "ANTHROPIC_SUMMARY_MODEL",
        ),
    )

    # Embedding
    embedding_model: str = "nomic-ai/nomic-embed-text-v1.5"
    embedding_dimensions: int = 768
    chunk_target_tokens: int = 300
    chunk_max_tokens: int = 400

    # Search
    search_mode: str = "hybrid"  # "vector", "hybrid", or "keyword"

    # Chat / persona / digest LLMs
    chat_model: str = Field(
        DEFAULT_CHAT_MODEL,
        validation_alias=AliasChoices(
            "chat_model",
            "CHAT_MODEL",
            "anthropic_chat_model",
            "ANTHROPIC_CHAT_MODEL",
        ),
    )
    persona_model: str = Field(
        DEFAULT_PERSONA_MODEL,
        validation_alias=AliasChoices(
            "persona_model",
            "PERSONA_MODEL",
            "anthropic_persona_model",
            "ANTHROPIC_PERSONA_MODEL",
        ),
    )
    digest_model: str = Field(
        DEFAULT_DIGEST_MODEL,
        validation_alias=AliasChoices(
            "digest_model",
            "DIGEST_MODEL",
            "anthropic_summary_model",
            "ANTHROPIC_SUMMARY_MODEL",
        ),
    )
    chat_max_history: int = 10
    chat_retrieval_top_k: int = 10

    # Telegram bot
    telegram_bot_token: str = ""
    telegram_allowed_users: list[int] = []
    telegram_notify_enabled: bool = True
    telegram_notify_muted_events: list[str] = []
    telegram_notify_state_path: str = "/tmp/yt-chatbot/notify_state.json"

    # Styled report delivery
    report_generation_enabled: bool = True
    report_delivery_enabled: bool = True
    report_artifact_dir: str = "data/reports"

    # Shared base URL the bot uses to call the web API (same host in practice)
    internal_web_base_url: str = "http://localhost:8000"

    # Native database URL (for processes running outside Docker)
    database_url_native: str = "postgresql+asyncpg://transcriber:transcriber@localhost:5432/transcriber"

    # API authentication (empty = dev mode, no auth required)
    api_key: str = ""

    # Persona generation tunables
    persona_min_videos: int = 3
    persona_refresh_after_videos: int = 5
    persona_characteristic_chunks: int = 30
    persona_exemplar_count: int = 5

    # Per-video duration limit
    max_video_duration_minutes: int = 120

    # Phase 3 recovery guardrails
    pipeline_manual_review_after_failures: int = 2
    # Queued-stall tolerance: how long a job can wait in the queue before
    # the reaper kills it. Default raised from 30 → 240 minutes because
    # autonomous backfills routinely queue 20+ videos and a serial audio
    # pipeline chews them at ~6/hr.
    pipeline_stale_timeout_queued_minutes: int = 240
    pipeline_stale_timeout_download_minutes: int = 90
    pipeline_stale_timeout_transcribe_minutes: int = 360
    pipeline_stale_timeout_diarize_minutes: int = 360
    pipeline_stale_timeout_cleanup_minutes: int = 60
    pipeline_stale_timeout_summarize_minutes: int = 60
    pipeline_stale_timeout_embed_minutes: int = 60

    # Daily LLM budget cap (USD)
    daily_llm_budget_usd: float = 5.0

    # Autonomous work budgets — prevent auto-ingest from blowing the overall cap.
    auto_ingest_daily_cost_cap_usd: float = 4.0
    auto_ingest_poll_hours_default: int = 24
    auto_ingest_max_videos_per_poll_default: int = 3

    # Library compression — a video untouched for N days has its WAV removed.
    # Transcript/summary/embeddings stay in Postgres; chat still works.
    compression_stale_days: int = 14
    compression_enabled: bool = True

    # yt-dlp authentication
    # Use a pre-exported cookies file (recommended for production)
    ytdlp_cookies_file: str = ""
    # OR pull cookies live from a browser ("chrome", "safari", etc.) — requires keychain access
    ytdlp_cookies_from_browser: str = ""

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    audio_dir: str = "/data/audio"
    model_cache_dir: str = "/data/models"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    @property
    def anthropic_cleanup_model(self) -> str:
        """Deprecated compatibility alias for ``cleanup_model``."""
        return self.cleanup_model

    @anthropic_cleanup_model.setter
    def anthropic_cleanup_model(self, value: str) -> None:
        self.cleanup_model = value

    @property
    def anthropic_summary_model(self) -> str:
        """Deprecated compatibility alias for ``summary_model``."""
        return self.summary_model

    @anthropic_summary_model.setter
    def anthropic_summary_model(self, value: str) -> None:
        self.summary_model = value

    @property
    def anthropic_chat_model(self) -> str:
        """Deprecated compatibility alias for ``chat_model``."""
        return self.chat_model

    @anthropic_chat_model.setter
    def anthropic_chat_model(self, value: str) -> None:
        self.chat_model = value

    @property
    def anthropic_persona_model(self) -> str:
        """Deprecated compatibility alias for ``persona_model``."""
        return self.persona_model

    @anthropic_persona_model.setter
    def anthropic_persona_model(self, value: str) -> None:
        self.persona_model = value


settings = Settings()
