"""Immutable, per-call snapshots for YouTube authentication cookies."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile
from typing import Iterator

from app.services.youtube_cookie_profiles import resolve_active_cookie_file


@contextmanager
def immutable_cookie_snapshot(
    cookie_path: str | Path | None = None,
) -> Iterator[str | None]:
    """Yield a protected disposable jar without exposing canonical state.

    yt-dlp may update its configured cookie file on exit. Every routine caller
    therefore receives a private copy; only the brokered refresh path may
    atomically replace the canonical jar.
    """
    configured = str(cookie_path or resolve_active_cookie_file() or "").strip()
    source = Path(configured).expanduser() if configured else None
    if source is None or not source.is_file():
        yield None
        return

    temp_dir = Path(tempfile.mkdtemp(prefix="yt-cookie-snapshot-"))
    snapshot = temp_dir / "youtube.txt"
    try:
        shutil.copyfile(source, snapshot)
        snapshot.chmod(0o600)
        yield str(snapshot)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
