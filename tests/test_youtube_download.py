from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from yt_dlp.utils import DownloadError

from app.config import settings
from app.services.youtube import download_audio, get_video_info


class _FakeYoutubeDL:
    calls: list[dict] = []
    outcomes: list[dict | Exception] = []

    def __init__(self, opts):
        self.opts = opts
        self.extract_info = MagicMock(side_effect=self._extract_info)
        self.__class__.calls.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def _extract_info(self, url, download=True):
        outcome = self.__class__.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def reset_fake_ytdl(monkeypatch):
    _FakeYoutubeDL.calls = []
    _FakeYoutubeDL.outcomes = []
    monkeypatch.setattr("app.services.youtube.yt_dlp.YoutubeDL", _FakeYoutubeDL)


def _info():
    return {
        "title": "Recovered video",
        "description": "desc",
        "duration": 123,
        "thumbnail": "https://example.com/thumb.jpg",
        "upload_date": "20260619",
    }


def test_download_audio_retries_without_cookies_after_cookie_backed_403(
    monkeypatch, tmp_path
):
    cookies = tmp_path / "youtube.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies))
    monkeypatch.setattr(settings, "ytdlp_cookies_from_browser", "")
    _FakeYoutubeDL.outcomes = [
        DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden"),
        _info(),
    ]

    result = download_audio("abc123XYZ09", str(tmp_path))

    assert result["title"] == "Recovered video"
    assert len(_FakeYoutubeDL.calls) == 2
    assert _FakeYoutubeDL.calls[0]["remote_components"] == ["ejs:github"]
    assert _FakeYoutubeDL.calls[0]["cookiefile"] == str(cookies)
    assert "cookiefile" not in _FakeYoutubeDL.calls[1]
    assert "cookiesfrombrowser" not in _FakeYoutubeDL.calls[1]


def test_download_audio_does_not_retry_non_403_download_errors(monkeypatch, tmp_path):
    cookies = tmp_path / "youtube.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(cookies))
    monkeypatch.setattr(settings, "ytdlp_cookies_from_browser", "")
    _FakeYoutubeDL.outcomes = [DownloadError("ERROR: video unavailable")]

    with pytest.raises(DownloadError, match="video unavailable"):
        download_audio("abc123XYZ09", str(tmp_path))

    assert len(_FakeYoutubeDL.calls) == 1


def test_download_audio_does_not_retry_403_when_cookies_are_not_enabled(
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
