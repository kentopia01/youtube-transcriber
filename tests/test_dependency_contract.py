from pathlib import Path
import tomllib


def test_ytdlp_floor_matches_validated_runtime_baseline():
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert "yt-dlp>=2026.6.9" in metadata["project"]["dependencies"]
