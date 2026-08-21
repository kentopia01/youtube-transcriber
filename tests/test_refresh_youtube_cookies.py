from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.youtube_download_hardening import ProbeResult
from scripts import refresh_youtube_cookies as mod


def _authenticated_cookie_text() -> str:
    return "\n".join(
        [
            "# Netscape HTTP Cookie File",
            ".youtube.com\tTRUE\t/\tTRUE\t4102444800\t__Secure-3PSID\tsecret",
            ".example.com\tTRUE\t/\tTRUE\t4102444800\tSID\tother-secret",
            "",
        ]
    )


class _FakeYoutubeDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url, download=False):
        Path(self.opts["cookiefile"]).write_text(_authenticated_cookie_text())
        return {"id": "probe", "title": "Probe"}


def test_filter_cookie_jar_removes_unrelated_domains_and_keeps_httponly(tmp_path):
    jar = tmp_path / "cookies.txt"
    jar.write_text(
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t4102444800\tSID\tsecret\n"
        ".accounts.google.com\tTRUE\t/\tTRUE\t4102444800\tSID\taccount-secret\n"
        ".example.com\tTRUE\t/\tTRUE\t4102444800\tSID\tother-secret\n"
    )

    mod.filter_cookie_jar(jar)

    content = jar.read_text()
    assert "youtube.com" in content
    assert "accounts.google.com" not in content
    assert "example.com" not in content
    assert oct(jar.stat().st_mode & 0o777) == "0o600"


def test_refresh_replaces_only_after_auth_lint_and_media_probe(monkeypatch, tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    cookie_file = tmp_path / "youtube.txt"
    cookie_file.write_text("old-cookie-jar\n")
    evidence_file = tmp_path / "status.json"
    monkeypatch.setattr(mod.yt_dlp, "YoutubeDL", _FakeYoutubeDL)
    monkeypatch.setattr(
        mod,
        "probe_youtube_media_download",
        lambda *args, **kwargs: ProbeResult(label="with_cookies", ok=True, title="Probe", duration=60),
    )

    evidence = mod.refresh_cookie_jar(
        profile_root=profile,
        cookie_file=cookie_file,
        evidence_file=evidence_file,
        probe_url="https://www.youtube.com/watch?v=probe",
    )

    assert evidence["status"] == "ok"
    assert evidence["production_replaced"] is True
    assert evidence["cookie_health"]["auth_cookie_count"] == 1
    assert "youtube.com" in cookie_file.read_text()
    assert "example.com" not in cookie_file.read_text()
    assert cookie_file.with_name("youtube.txt.previous").read_text() == "old-cookie-jar\n"
    assert json.loads(evidence_file.read_text())["media_probe"]["ok"] is True


def test_refresh_requires_every_configured_canary_to_pass(monkeypatch, tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    cookie_file = tmp_path / "youtube.txt"
    cookie_file.write_text("last-known-good\n")
    evidence_file = tmp_path / "status.json"
    monkeypatch.setattr(mod.yt_dlp, "YoutubeDL", _FakeYoutubeDL)
    probes = iter(
        [
            ProbeResult(label="with_cookies", ok=True, title="First", duration=60),
            ProbeResult(label="with_cookies", ok=False, error="second canary failed"),
        ]
    )
    monkeypatch.setattr(
        mod,
        "probe_youtube_media_download",
        lambda *args, **kwargs: next(probes),
    )

    with pytest.raises(mod.CookieRefreshError, match="one canary"):
        mod.refresh_cookie_jar(
            profile_root=profile,
            cookie_file=cookie_file,
            evidence_file=evidence_file,
            probe_urls=[
                "https://www.youtube.com/watch?v=first",
                "https://www.youtube.com/watch?v=second",
            ],
        )

    assert cookie_file.read_text() == "last-known-good\n"
    evidence = json.loads(evidence_file.read_text())
    assert len(evidence["media_probes"]) == 2
    assert evidence["production_replaced"] is False


def test_successful_refresh_synchronizes_configured_profile_state(monkeypatch, tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    cookie_file = tmp_path / "youtube.txt"
    cookie_file.write_text("old-cookie-jar\n")
    state_file = tmp_path / "profiles.json"
    evidence_file = tmp_path / "status.json"
    monkeypatch.setattr(mod.settings, "ytdlp_cookies_file", str(cookie_file))
    monkeypatch.setattr(mod.settings, "ytdlp_cookie_profile_state_file", str(state_file))
    monkeypatch.setattr(mod.yt_dlp, "YoutubeDL", _FakeYoutubeDL)
    monkeypatch.setattr(
        mod,
        "probe_youtube_media_download",
        lambda *args, **kwargs: ProbeResult(label="with_cookies", ok=True),
    )

    mod.refresh_cookie_jar(
        profile_root=profile,
        cookie_file=cookie_file,
        evidence_file=evidence_file,
        probe_urls=[
            "https://www.youtube.com/watch?v=first",
            "https://www.youtube.com/watch?v=second",
        ],
    )

    state = json.loads(state_file.read_text())
    assert state["profiles"]["profile_a"]["last_probe_ok"] is True
    assert state["profiles"]["profile_a"]["last_error"] is None


def test_anonymous_candidate_preserves_production_jar(monkeypatch, tmp_path):
    class _AnonymousYoutubeDL(_FakeYoutubeDL):
        def extract_info(self, url, download=False):
            Path(self.opts["cookiefile"]).write_text(
                "# Netscape HTTP Cookie File\n"
                ".youtube.com\tTRUE\t/\tTRUE\t4102444800\tVISITOR_INFO1_LIVE\tvisitor\n"
            )
            return {"id": "probe"}

    profile = tmp_path / "profile"
    profile.mkdir()
    cookie_file = tmp_path / "youtube.txt"
    cookie_file.write_text("last-known-good\n")
    evidence_file = tmp_path / "status.json"
    monkeypatch.setattr(mod.yt_dlp, "YoutubeDL", _AnonymousYoutubeDL)
    monkeypatch.setattr(
        mod,
        "probe_youtube_media_download",
        lambda *args, **kwargs: pytest.fail("media probe must not run for anonymous cookies"),
    )

    with pytest.raises(mod.CookieRefreshError, match="anonymous_only"):
        mod.refresh_cookie_jar(
            profile_root=profile,
            cookie_file=cookie_file,
            evidence_file=evidence_file,
            probe_url="https://www.youtube.com/watch?v=probe",
        )

    assert cookie_file.read_text() == "last-known-good\n"
    evidence = json.loads(evidence_file.read_text())
    assert evidence["status"] == "failed"
    assert evidence["production_replaced"] is False


def test_broker_command_uses_nora_identity_and_internal_mode(tmp_path):
    args = SimpleNamespace(
        broker=tmp_path / "browser-broker",
        idempotency_key="test-key",
        profile_root=tmp_path / "profile",
        profile_resource="identity:nora-work-b",
        cookie_file=tmp_path / "youtube.txt",
        evidence_file=tmp_path / "status.json",
        probe_url="https://www.youtube.com/watch?v=probe",
    )

    command = mod.build_broker_command(args)

    assert command[command.index("--resource") + 1] == "identity:nora-work-b"
    assert command[command.index("--idempotency-key") + 1] == "test-key"
    assert "--inside-broker" in command
    inner_index = command.index("--")
    assert command[inner_index + 1 :].count("--profile-resource") == 1
