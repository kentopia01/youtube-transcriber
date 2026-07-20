"""Small, dependency-light helpers shared by native operator scripts."""

from __future__ import annotations

import os
from pathlib import Path


def read_env_value(path: Path, key: str) -> str | None:
    """Read one simple KEY=VALUE entry without mutating process environment."""
    if not path.exists():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return None


def load_native_env(project_root: Path) -> None:
    """Load missing values from .env.native without overriding the caller."""
    native_env = project_root / ".env.native"
    if not native_env.exists():
        return
    for raw_line in native_env.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def syncify_database_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")


def resolve_sync_database_url(
    project_root: Path,
    *,
    explicit: str | None = None,
    fallback: str | None = None,
) -> str:
    """Resolve a native sync DB URL using one consistent precedence order."""
    candidates = (
        explicit,
        os.environ.get("DATABASE_URL_SYNC"),
        os.environ.get("DATABASE_URL_NATIVE"),
        read_env_value(project_root / ".env.native", "DATABASE_URL_SYNC"),
        read_env_value(project_root / ".env.native", "DATABASE_URL_NATIVE"),
        read_env_value(project_root / ".env.native", "DATABASE_URL"),
        fallback,
    )
    for candidate in candidates:
        if candidate:
            return syncify_database_url(candidate)

    # Lazy import keeps this helper usable before application settings are loaded.
    from app.config import settings

    return syncify_database_url(settings.database_url_sync)
