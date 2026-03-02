from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://transcriber:transcriber@postgres:5432/transcriber"
    database_url_sync: str = "postgresql+psycopg2://transcriber:transcriber@postgres:5432/transcriber"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Claude API
    anthropic_api_key: str = ""

    # Whisper
    whisper_model_size: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    audio_dir: str = "/data/audio"
    model_cache_dir: str = "/data/models"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
