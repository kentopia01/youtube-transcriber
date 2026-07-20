import os

from app.services.runtime_config import (
    load_native_env,
    read_env_value,
    resolve_sync_database_url,
    syncify_database_url,
)


def test_load_native_env_parses_comments_and_preserves_existing_values(tmp_path, monkeypatch):
    (tmp_path / ".env.native").write_text(
        "# comment\nEXISTING=replaced\nQUOTED='native value'\nINVALID\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EXISTING", "caller")
    monkeypatch.delenv("QUOTED", raising=False)

    load_native_env(tmp_path)

    assert read_env_value(tmp_path / ".env.native", "QUOTED") == "native value"
    assert os.environ["EXISTING"] == "caller"
    assert os.environ["QUOTED"] == "native value"


def test_resolve_sync_database_url_uses_consistent_precedence(tmp_path, monkeypatch):
    (tmp_path / ".env.native").write_text(
        "DATABASE_URL_SYNC=postgresql+psycopg2://file-sync\n"
        "DATABASE_URL_NATIVE=postgresql+asyncpg://file-native\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql+asyncpg://environment")
    monkeypatch.setenv("DATABASE_URL_NATIVE", "postgresql+asyncpg://environment-native")

    assert resolve_sync_database_url(
        tmp_path,
        explicit="postgresql+asyncpg://explicit",
        fallback="postgresql+asyncpg://fallback",
    ) == "postgresql+psycopg2://explicit"
    assert resolve_sync_database_url(tmp_path) == "postgresql+psycopg2://environment"


def test_resolve_sync_database_url_falls_back_through_native_file(tmp_path, monkeypatch):
    (tmp_path / ".env.native").write_text(
        "DATABASE_URL_NATIVE='postgresql+asyncpg://native-file'\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
    monkeypatch.delenv("DATABASE_URL_NATIVE", raising=False)

    assert resolve_sync_database_url(
        tmp_path,
        fallback="postgresql+asyncpg://fallback",
    ) == "postgresql+psycopg2://native-file"


def test_syncify_database_url_leaves_sync_drivers_unchanged():
    assert syncify_database_url("postgresql+psycopg2://db") == "postgresql+psycopg2://db"
