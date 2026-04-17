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
    cleanup_model: str = "claude-haiku-4-5-20251001"

    # LLM summarization
    summary_model: str = "claude-haiku-4-5-20251001"

    # Embedding
    embedding_model: str = "nomic-ai/nomic-embed-text-v1.5"
    embedding_dimensions: int = 768
    chunk_target_tokens: int = 300
    chunk_max_tokens: int = 400

    # Search
    search_mode: str = "hybrid"  # "vector", "hybrid", or "keyword"

    # Chat
    chat_model: str = "claude-sonnet-4-20250514"
    chat_max_history: int = 10
    chat_retrieval_top_k: int = 10

    # Telegram bot
    telegram_bot_token: str = ""
    telegram_allowed_users: list[int] = []
    telegram_notify_enabled: bool = True
    telegram_notify_muted_events: list[str] = []
    telegram_notify_state_path: str = "/tmp/yt-chatbot/notify_state.json"
    # Shared base URL the bot uses to call the web API (same host in practice)
    internal_web_base_url: str = "http://localhost:8000"

    # Native database URL (for processes running outside Docker)
    database_url_native: str = "postgresql+asyncpg://transcriber:transcriber@localhost:5432/transcriber"

    # API authentication (empty = dev mode, no auth required)
    api_key: str = ""

    # LLM models (explicit per-use-case settings)
    anthropic_cleanup_model: str = "claude-haiku-4-5"
    anthropic_chat_model: str = "claude-haiku-4-5"
    anthropic_summary_model: str = "claude-sonnet-4-5"
    anthropic_persona_model: str = "claude-sonnet-4-5"

    # Persona generation tunables
    persona_min_videos: int = 3
    persona_refresh_after_videos: int = 5
    persona_characteristic_chunks: int = 30
    persona_exemplar_count: int = 5

    # Per-video duration limit
    max_video_duration_minutes: int = 120

    # Phase 3 recovery guardrails
    pipeline_manual_review_after_failures: int = 2
    pipeline_stale_timeout_queued_minutes: int = 30
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

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
