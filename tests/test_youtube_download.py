from __future__ import annotations

from unittest.mock import MagicMock
from pathlib import Path
from types import SimpleNamespace

import pytest
from yt_dlp.utils import DownloadError

from app.config import settings
from app.services.youtube import discover_channel_videos, download_audio, get_video_info
from app.services.youtube_cookie_profiles import activate_profile, record_profile_probe


class _FakeYoutubeDL:
    calls: list[dict] = []
    outcomes: list[dict | Exception] = []
    cookie_contents: list[str] = []
    mutate_cookie_snapshot = False

    def __init__(self, opts):
        self.opts = opts
        self.extract_info = MagicMock(side_effect=self._extract_info)
        self.__class__.calls.append(opts)
        if "cookiefile" in opts:
            self.__class__.cookie_contents.append(
                Path(opts["cookiefile"]).read_text()
            )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def _extract_info(self, url, download=True):
        if self.__class__.mutate_cookie_snapshot and "cookiefile" in self.opts:
            Path(self.opts["cookiefile"]).write_text("yt-dlp refreshed snapshot\n")
        outcome = self.__class__.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def reset_fake_ytdl(monkeypatch):
    _FakeYoutubeDL.calls = []
    _FakeYoutubeDL.outcomes = []
    _FakeYoutubeDL.cookie_contents = []
    _FakeYoutubeDL.mutate_cookie_snapshot = False
    monkeypatch.setattr("app.services.youtube.yt_dlp.YoutubeDL", _FakeYoutubeDL)
    monkeypatch.setattr(
        "app.services.youtube.require_authenticated_access_ready",
        lambda: SimpleNamespace(client="mweb"),
    )


def _info():
    return {
        "title": "Recovered video",
        "description": "desc",
        "duration": 123,
        "thumbnail": "https://example.com/thumb.jpg",
        "upload_date": "20260619",
    }


def test_download_audio_is_anonymous_for_public_video(monkeypatch, tmp_path):
    cookies = tmp_path / "youtube.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies))
    monkeypatch.setattr(settings, "ytdlp_cookies_from_browser", "")
    _FakeYoutubeDL.outcomes = [_info()]

    result = download_audio("abc123XYZ09", str(tmp_path))

    assert result["title"] == "Recovered video"
    assert len(_FakeYoutubeDL.calls) == 1
    assert _FakeYoutubeDL.calls[0]["remote_components"] == ["ejs:github"]
    assert "cookiefile" not in _FakeYoutubeDL.calls[0]
    assert "cookiesfrombrowser" not in _FakeYoutubeDL.calls[0]


def test_download_audio_uses_auth_only_after_explicit_requirement(monkeypatch, tmp_path):
    cookies = tmp_path / "youtube.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies))
    monkeypatch.setattr(settings, "ytdlp_cookies_from_browser", "")
    _FakeYoutubeDL.outcomes = [
        DownloadError("ERROR: Sign in to confirm your age"),
        _info(),
    ]

    result = download_audio("abc123XYZ09", str(tmp_path))

    assert result["title"] == "Recovered video"
    assert len(_FakeYoutubeDL.calls) == 2
    assert "cookiefile" not in _FakeYoutubeDL.calls[0]
    snapshot = Path(_FakeYoutubeDL.calls[1]["cookiefile"])
    assert snapshot != cookies
    assert not snapshot.exists()
    assert _FakeYoutubeDL.cookie_contents == ["# Netscape HTTP Cookie File\n"]
    assert _FakeYoutubeDL.calls[1]["extractor_args"] == {
        "youtube": {"player_client": ["mweb"]}
    }


def test_download_audio_retries_exact_url_anonymously_after_auth_session_degrades(
    monkeypatch, tmp_path
):
    cookies = tmp_path / "youtube.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies))
    monkeypatch.setattr(settings, "ytdlp_cookies_from_browser", "")
    _FakeYoutubeDL.outcomes = [
        DownloadError("ERROR: Sign in to confirm your age"),
        DownloadError("ERROR: Video unavailable"),
        _info(),
    ]

    result = download_audio("abc123XYZ09", str(tmp_path))

    assert result["title"] == "Recovered video"
    assert len(_FakeYoutubeDL.calls) == 3
    assert "cookiefile" not in _FakeYoutubeDL.calls[0]
    assert Path(_FakeYoutubeDL.calls[1]["cookiefile"]) != cookies
    assert not Path(_FakeYoutubeDL.calls[1]["cookiefile"]).exists()
    assert "cookiefile" not in _FakeYoutubeDL.calls[2]


def test_download_audio_does_not_auth_retry_generic_unavailable(monkeypatch, tmp_path):
    cookies = tmp_path / "youtube.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies))
    monkeypatch.setattr(settings, "ytdlp_cookies_from_browser", "")
    _FakeYoutubeDL.outcomes = [DownloadError("ERROR: video unavailable")]

    with pytest.raises(DownloadError, match="video unavailable"):
        download_audio("abc123XYZ09", str(tmp_path))

    assert len(_FakeYoutubeDL.calls) == 1


def test_download_audio_does_not_auth_retry_403_when_anonymous(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "ytdlp_cookies_file", "")
    monkeypatch.setattr(settings, "ytdlp_cookies_from_browser", "")
    _FakeYoutubeDL.outcomes = [
        DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden")
    ]

    with pytest.raises(DownloadError, match="HTTP Error 403"):
        download_audio("abc123XYZ09", str(tmp_path))

    assert len(_FakeYoutubeDL.calls) == 1


def test_get_video_info_allows_metadata_without_selectable_formats(monkeypatch):
    monkeypatch.setattr(settings, "ytdlp_cookies_file", "")
    monkeypatch.setattr(settings, "ytdlp_cookies_from_browser", "")
    _FakeYoutubeDL.outcomes = [
        {
            "id": "abc123XYZ09",
            "title": "Metadata-only video",
            "webpage_url": "https://www.youtube.com/watch?v=abc123XYZ09",
        }
    ]

    result = get_video_info("https://www.youtube.com/watch?v=abc123XYZ09")

    assert result["video_id"] == "abc123XYZ09"
    assert _FakeYoutubeDL.calls[0]["skip_download"] is True
    assert _FakeYoutubeDL.calls[0]["ignore_no_formats_error"] is True
    assert _FakeYoutubeDL.calls[0]["remote_components"] == ["ejs:github"]


def test_get_video_info_is_anonymous_even_when_cookies_are_configured(monkeypatch, tmp_path):
    cookies = tmp_path / "youtube.txt"
    cookies.write_text("cookie data")
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies))
    monkeypatch.setattr(settings, "ytdlp_cookies_from_browser", "")
    _FakeYoutubeDL.outcomes = [
        {
            "id": "abc123XYZ09",
            "title": "Public metadata",
            "webpage_url": "https://www.youtube.com/watch?v=abc123XYZ09",
        }
    ]

    get_video_info("https://www.youtube.com/watch?v=abc123XYZ09")

    assert "cookiefile" not in _FakeYoutubeDL.calls[0]


def test_get_video_info_resolves_persisted_active_cookie_profile(monkeypatch, tmp_path):
    profile_a = tmp_path / "profile-a.txt"
    profile_b = tmp_path / "profile-b.txt"
    state_file = tmp_path / "state.json"
    profile_a.write_text("a")
    profile_b.write_text("b")
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(profile_a))
    monkeypatch.setattr(settings, "ytdlp_cookie_profile_b_file", str(profile_b))
    monkeypatch.setattr(settings, "ytdlp_cookie_profile_state_file", str(state_file))
    monkeypatch.setattr(settings, "ytdlp_cookie_profile_probe_max_age_seconds", 3600)
    record_profile_probe("profile_b", ok=True)
    activate_profile("profile_b")
    _FakeYoutubeDL.outcomes = [
        DownloadError("ERROR: This video is private"),
        {
            "id": "abc123XYZ09",
            "title": "Profile B metadata",
            "webpage_url": "https://www.youtube.com/watch?v=abc123XYZ09",
        }
    ]

    get_video_info("https://www.youtube.com/watch?v=abc123XYZ09")

    assert "cookiefile" not in _FakeYoutubeDL.calls[0]
    assert Path(_FakeYoutubeDL.calls[1]["cookiefile"]) != profile_b
    assert _FakeYoutubeDL.cookie_contents == ["b"]
    assert not Path(_FakeYoutubeDL.calls[1]["cookiefile"]).exists()


def test_authenticated_extraction_cannot_mutate_canonical_cookie_jar(monkeypatch, tmp_path):
    cookies = tmp_path / "youtube.txt"
    original = "# Netscape HTTP Cookie File\ncanonical-cookie-state\n"
    cookies.write_text(original)
    before_mtime = cookies.stat().st_mtime_ns
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies))
    monkeypatch.setattr(settings, "ytdlp_cookies_from_browser", "")
    _FakeYoutubeDL.mutate_cookie_snapshot = True
    _FakeYoutubeDL.outcomes = [
        DownloadError("ERROR: Sign in to confirm your age"),
        _info(),
    ]

    download_audio("abc123XYZ09", str(tmp_path))

    assert cookies.read_text() == original
    assert cookies.stat().st_mtime_ns == before_mtime


def test_channel_discovery_is_anonymous_for_public_channels(monkeypatch, tmp_path):
    cookies = tmp_path / "youtube.txt"
    cookies.write_text("cookie data")
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies))
    monkeypatch.setattr(settings, "ytdlp_cookies_from_browser", "")
    _FakeYoutubeDL.outcomes = [
        {
            "id": "UC-test",
            "title": "Test Channel",
            "entries": [],
        }
    ]

    discover_channel_videos("https://www.youtube.com/@test")

    assert "cookiefile" not in _FakeYoutubeDL.calls[0]
