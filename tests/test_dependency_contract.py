from pathlib import Path
import tomllib


def test_dependency_floors_match_validated_runtime_baseline():
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert "yt-dlp==2026.8.19" in metadata["project"]["dependencies"]
    assert "anthropic>=0.117.0,<1.0.0" in metadata["project"]["dependencies"]


def test_web_image_uses_cpu_torch_and_only_web_ml_extra():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert "torch==2.11.0" in dockerfile
    assert "https://download.pytorch.org/whl/cpu" in dockerfile
    assert '".[web]"' in dockerfile
    assert "ARG DENO_VERSION=2.7.11" in dockerfile
    assert "deno --version" in dockerfile
    assert "sentence-transformers>=3.3.0" in metadata["project"]["optional-dependencies"]["web"]
