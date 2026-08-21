"""Runtime parity contract for YouTube extraction paths."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import shutil

import yt_dlp


REQUIRED_YTDLP_VERSION = "2026.08.19"
REQUIRED_JS_RUNTIME = "deno"


def _version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return ()


@dataclass(slots=True)
class YouTubeRuntimeStatus:
    ok: bool
    yt_dlp_version: str
    required_yt_dlp_version: str
    yt_dlp_matches: bool
    js_runtime: str
    js_runtime_path: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def inspect_youtube_runtime() -> YouTubeRuntimeStatus:
    version = yt_dlp.version.__version__
    version_matches = _version_tuple(version) == _version_tuple(REQUIRED_YTDLP_VERSION)
    js_path = shutil.which(REQUIRED_JS_RUNTIME)
    return YouTubeRuntimeStatus(
        ok=version_matches and bool(js_path),
        yt_dlp_version=version,
        required_yt_dlp_version=REQUIRED_YTDLP_VERSION,
        yt_dlp_matches=version_matches,
        js_runtime=REQUIRED_JS_RUNTIME,
        js_runtime_path=js_path,
    )
