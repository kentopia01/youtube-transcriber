from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_ANTHROPIC_CLEANUP_MODEL = "claude-haiku-4-5"
DEFAULT_CLEANUP_MODEL = "yt-cleanup"
DEFAULT_ANTHROPIC_SUMMARY_MODEL = "claude-sonnet-4-5"
DEFAULT_SUMMARY_MODEL = "yt-summary"
DEFAULT_ANTHROPIC_CHAT_MODEL = "claude-haiku-4-5"
DEFAULT_CHAT_MODEL = "yt-chat"
DEFAULT_ANTHROPIC_PERSONA_MODEL = "claude-sonnet-4-5"
DEFAULT_PERSONA_MODEL = "yt-persona"
DEFAULT_ANTHROPIC_DIGEST_MODEL = "claude-sonnet-4-5"
DEFAULT_DIGEST_MODEL = "yt-digest"


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
    diarization_mode: str = Field(
        "deferred",
        validation_alias=AliasChoices("diarization_mode", "DIARIZATION_MODE"),
    )
    transcript_cleanup_enabled: bool = False

    @property
    def inline_diarization_enabled(self) -> bool:
        return (
            self.diarization_enabled
            and bool(self.hf_token)
            and (self.diarization_mode or "").strip().lower() == "inline"
        )

    # Canonical model settings. Use these env vars for new config.
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
    warm_embedding_model: bool = False

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
    summary_llm_provider: str = Field(
        "openai_compatible",
        validation_alias=AliasChoices("summary_llm_provider", "SUMMARY_LLM_PROVIDER"),
    )
    cleanup_llm_provider: str = Field(
        "openai_compatible",
        validation_alias=AliasChoices("cleanup_llm_provider", "CLEANUP_LLM_PROVIDER"),
    )
    cleanup_llm_base_url: str = Field(
        "http://127.0.0.1:8400/v1",
        validation_alias=AliasChoices("cleanup_llm_base_url", "CLEANUP_LLM_BASE_URL"),
    )
    cleanup_llm_api_key: str = Field(
        "",
        validation_alias=AliasChoices("cleanup_llm_api_key", "CLEANUP_LLM_API_KEY"),
    )
    cleanup_llm_fallback_provider: str = Field(
        "anthropic",
        validation_alias=AliasChoices("cleanup_llm_fallback_provider", "CLEANUP_LLM_FALLBACK_PROVIDER"),
    )
    cleanup_llm_fallback_model: str = Field(
        DEFAULT_ANTHROPIC_CLEANUP_MODEL,
        validation_alias=AliasChoices("cleanup_llm_fallback_model", "CLEANUP_LLM_FALLBACK_MODEL"),
    )
    summary_llm_base_url: str = Field(
        "http://127.0.0.1:8400/v1",
        validation_alias=AliasChoices("summary_llm_base_url", "SUMMARY_LLM_BASE_URL"),
    )
    summary_llm_api_key: str = Field(
        "",
        validation_alias=AliasChoices("summary_llm_api_key", "SUMMARY_LLM_API_KEY"),
    )
    summary_llm_fallback_provider: str = Field(
        "anthropic",
        validation_alias=AliasChoices("summary_llm_fallback_provider", "SUMMARY_LLM_FALLBACK_PROVIDER"),
    )
    summary_llm_fallback_model: str = Field(
        DEFAULT_ANTHROPIC_SUMMARY_MODEL,
        validation_alias=AliasChoices("summary_llm_fallback_model", "SUMMARY_LLM_FALLBACK_MODEL"),
    )
    chat_llm_provider: str = Field(
        "openai_compatible",
        validation_alias=AliasChoices("chat_llm_provider", "CHAT_LLM_PROVIDER"),
    )
    chat_llm_base_url: str = Field(
        "http://127.0.0.1:8400/v1",
        validation_alias=AliasChoices("chat_llm_base_url", "CHAT_LLM_BASE_URL"),
    )
    chat_llm_api_key: str = Field(
        "",
        validation_alias=AliasChoices("chat_llm_api_key", "CHAT_LLM_API_KEY"),
    )
    chat_llm_fallback_provider: str = Field(
        "anthropic",
        validation_alias=AliasChoices("chat_llm_fallback_provider", "CHAT_LLM_FALLBACK_PROVIDER"),
    )
    chat_llm_fallback_model: str = Field(
        DEFAULT_ANTHROPIC_CHAT_MODEL,
        validation_alias=AliasChoices("chat_llm_fallback_model", "CHAT_LLM_FALLBACK_MODEL"),
    )
    persona_llm_provider: str = Field(
        "openai_compatible",
        validation_alias=AliasChoices("persona_llm_provider", "PERSONA_LLM_PROVIDER"),
    )
    persona_llm_base_url: str = Field(
        "http://127.0.0.1:8400/v1",
        validation_alias=AliasChoices("persona_llm_base_url", "PERSONA_LLM_BASE_URL"),
    )
    persona_llm_api_key: str = Field(
        "",
        validation_alias=AliasChoices("persona_llm_api_key", "PERSONA_LLM_API_KEY"),
    )
    persona_llm_fallback_provider: str = Field(
        "anthropic",
        validation_alias=AliasChoices("persona_llm_fallback_provider", "PERSONA_LLM_FALLBACK_PROVIDER"),
    )
    persona_llm_fallback_model: str = Field(
        DEFAULT_ANTHROPIC_PERSONA_MODEL,
        validation_alias=AliasChoices("persona_llm_fallback_model", "PERSONA_LLM_FALLBACK_MODEL"),
    )
    digest_llm_provider: str = Field(
        "openai_compatible",
        validation_alias=AliasChoices("digest_llm_provider", "DIGEST_LLM_PROVIDER"),
    )
    digest_llm_base_url: str = Field(
        "http://127.0.0.1:8400/v1",
        validation_alias=AliasChoices("digest_llm_base_url", "DIGEST_LLM_BASE_URL"),
    )
    digest_llm_api_key: str = Field(
        "",
        validation_alias=AliasChoices("digest_llm_api_key", "DIGEST_LLM_API_KEY"),
    )
    digest_llm_fallback_provider: str = Field(
        "anthropic",
        validation_alias=AliasChoices("digest_llm_fallback_provider", "DIGEST_LLM_FALLBACK_PROVIDER"),
    )
    digest_llm_fallback_model: str = Field(
        DEFAULT_ANTHROPIC_DIGEST_MODEL,
        validation_alias=AliasChoices("digest_llm_fallback_model", "DIGEST_LLM_FALLBACK_MODEL"),
    )
    chat_max_history: int = 10
    chat_retrieval_top_k: int = 10

    # Telegram bot
    telegram_bot_token: str = ""
    telegram_allowed_users: list[int] = []
    telegram_admin_users: list[int] = []
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
    max_video_duration_minutes: int = 250

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
    # A stale attempt may be re-enqueued once when durable artifacts prove the
    # previous stage committed but the next Celery handoff was lost.
    pipeline_stale_handoff_recovery_limit: int = 1

    # Daily LLM budget cap (USD). Set to 0 to disable.
    daily_llm_budget_usd: float = 0.0

    # Autonomous work budgets — prevent auto-ingest from blowing the overall cap.
    auto_ingest_daily_cost_cap_usd: float = 4.0
    auto_ingest_poll_hours_default: int = 24
    auto_ingest_max_videos_per_poll_default: int = 3
    # Bound each poll invocation across all subscriptions. Hourly due checks
    # drain larger backlogs gradually without flooding the audio queue.
    auto_ingest_max_submissions_per_run: int = 3
    # Subscription auto-ingest is for long-form signal, not Shorts/reels/clips.
    # Set to 0 to disable the long-form duration floor.
    auto_ingest_min_duration_seconds: int = 600

    # Library compression — a video untouched for N days has its WAV removed.
    # Transcript/summary/embeddings stay in Postgres; chat still works.
    compression_stale_days: int = 14
    compression_enabled: bool = True

    # yt-dlp authentication
    # Use a pre-exported cookies file (recommended for production)
    ytdlp_cookies_file: str = ""
    # OR pull cookies live from a browser ("chrome", "safari", etc.) — requires keychain access
    ytdlp_cookies_from_browser: str = ""
    # Optional dormant second jar. Selection remains explicit and manual.
    ytdlp_cookie_profile_b_file: str = ""
    # Empty derives a protected state file beside Profile A's jar.
    ytdlp_cookie_profile_state_file: str = ""
    ytdlp_cookie_profile_probe_max_age_seconds: int = 86400
    ytdlp_cookie_profile_failure_cooldown_seconds: int = 1800
    # Authenticated extraction is disabled until a maintained PO-token provider
    # is explicitly configured and discovered by yt-dlp's plugin registry.
    ytdlp_authenticated_access_enabled: bool = False
    ytdlp_po_token_provider_name: str = ""
    ytdlp_po_token_client: str = "mweb"

    # YouTube access-degradation circuit. Distinct-video failures within the
    # window open a self-expiring pause for autonomous subscription ingest.
    download_circuit_enabled: bool = True
    download_circuit_failure_threshold: int = 2
    download_circuit_window_seconds: int = 600
    download_circuit_cooldown_seconds: int = 1800

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    audio_dir: str = "/data/audio"
    model_cache_dir: str = "/data/models"
    mutation_audit_path: str = "data/audit/mutations.jsonl"

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
