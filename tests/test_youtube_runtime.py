from app.services import youtube_runtime as mod


def test_runtime_accepts_normalized_required_version_and_deno(monkeypatch):
    monkeypatch.setattr(mod.yt_dlp.version, "__version__", "2026.8.19")
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/deno")

    status = mod.inspect_youtube_runtime()

    assert status.ok is True
    assert status.yt_dlp_matches is True
    assert status.js_runtime == "deno"


def test_runtime_fails_closed_on_version_or_js_drift(monkeypatch):
    monkeypatch.setattr(mod.yt_dlp.version, "__version__", "2026.7.4")
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)

    status = mod.inspect_youtube_runtime()

    assert status.ok is False
    assert status.yt_dlp_matches is False
    assert status.js_runtime_path is None
