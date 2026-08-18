from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

import pytest

from app.config import settings
from app.services.youtube_download_hardening import ProbeResult
from app.services import youtube_cookie_profiles as profiles
from scripts import manage_youtube_cookie_profiles as cli


def _authenticated_cookie_text(name: str = "__Secure-3PSID") -> str:
    return (
        "# Netscape HTTP Cookie File\n"
        f".youtube.com\tTRUE\t/\tTRUE\t4102444800\t{name}\tsecret\n"
    )


@pytest.fixture
def profile_config(monkeypatch, tmp_path):
    profile_a = tmp_path / "profile-a.txt"
    profile_b = tmp_path / "profile-b.txt"
    state_file = tmp_path / "profile-state.json"
    profile_a.write_text(_authenticated_cookie_text())
    profile_b.write_text(_authenticated_cookie_text("SAPISID"))
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(profile_a))
    monkeypatch.setattr(settings, "ytdlp_cookie_profile_b_file", str(profile_b))
    monkeypatch.setattr(settings, "ytdlp_cookie_profile_state_file", str(state_file))
    monkeypatch.setattr(settings, "ytdlp_cookie_profile_probe_max_age_seconds", 3600)
    monkeypatch.setattr(settings, "ytdlp_cookie_profile_failure_cooldown_seconds", 600)
    return profile_a, profile_b, state_file


def test_legacy_single_file_defaults_to_profile_a(monkeypatch, tmp_path):
    profile_a = tmp_path / "youtube.txt"
    profile_a.write_text(_authenticated_cookie_text())
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(profile_a))
    monkeypatch.setattr(settings, "ytdlp_cookie_profile_b_file", "")
    monkeypatch.setattr(settings, "ytdlp_cookie_profile_state_file", "")

    assert profiles.resolve_active_profile() == profiles.PROFILE_A
    assert profiles.resolve_active_cookie_file() == str(profile_a)


def test_invalid_or_unconfigured_profile_b_state_falls_back_to_a(
    monkeypatch, tmp_path
):
    profile_a = tmp_path / "youtube.txt"
    profile_a.write_text(_authenticated_cookie_text())
    state_file = tmp_path / "state.json"
    state_file.write_text("{invalid")
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(profile_a))
    monkeypatch.setattr(settings, "ytdlp_cookie_profile_b_file", "")
    monkeypatch.setattr(settings, "ytdlp_cookie_profile_state_file", str(state_file))

    assert profiles.resolve_active_profile() == profiles.PROFILE_A

    state_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_profile": "profile_b",
                "profiles": {},
            }
        )
    )
    assert profiles.resolve_active_profile() == profiles.PROFILE_A


def test_failed_probe_records_cooldown_and_blocks_activation(profile_config):
    _, _, state_file = profile_config
    now = datetime(2026, 8, 18, 3, 0, tzinfo=UTC)

    state = profiles.record_profile_probe(
        profiles.PROFILE_B,
        ok=False,
        error="media probe failed",
        now=now,
    )

    assert state["profiles"][profiles.PROFILE_B]["last_probe_ok"] is False
    assert state["profiles"][profiles.PROFILE_B]["cooldown_until"] == (
        now + timedelta(seconds=600)
    ).isoformat()
    with pytest.raises(profiles.CookieProfileError, match="cooling down"):
        profiles.activate_profile(profiles.PROFILE_B, now=now + timedelta(seconds=1))
    assert oct(state_file.stat().st_mode & 0o777) == "0o600"


def test_stale_successful_probe_blocks_activation(profile_config):
    _, _, _ = profile_config
    probed_at = datetime(2026, 8, 18, 3, 0, tzinfo=UTC)
    profiles.record_profile_probe(profiles.PROFILE_B, ok=True, now=probed_at)

    with pytest.raises(profiles.CookieProfileError, match="stale"):
        profiles.activate_profile(
            profiles.PROFILE_B,
            now=probed_at + timedelta(seconds=3601),
        )


def test_confirmed_switch_and_failback_persist(profile_config):
    profile_a, profile_b, _ = profile_config
    now = datetime(2026, 8, 18, 3, 0, tzinfo=UTC)
    profiles.record_profile_probe(profiles.PROFILE_B, ok=True, now=now)
    profiles.activate_profile(profiles.PROFILE_B, now=now)

    assert profiles.resolve_active_profile() == profiles.PROFILE_B
    assert profiles.resolve_active_cookie_file() == str(profile_b)

    profiles.record_profile_probe(profiles.PROFILE_A, ok=True, now=now)
    profiles.activate_profile(profiles.PROFILE_A, now=now)
    assert profiles.load_profile_state()["active_profile"] == profiles.PROFILE_A
    assert profiles.resolve_active_cookie_file() == str(profile_a)


def test_operator_commands_require_probe_and_confirmation(
    monkeypatch, profile_config, capsys
):
    _, _, state_file = profile_config
    monkeypatch.setattr(
        cli,
        "probe_youtube_media_download",
        lambda *args, **kwargs: ProbeResult(
            label="with_cookies",
            ok=True,
            title="Probe",
            duration=60,
            downloaded_bytes=1024,
        ),
    )

    assert cli.main(["--state-file", str(state_file), "activate", "profile_b"]) == 2
    assert "without --confirm" in capsys.readouterr().err

    assert cli.main(["--state-file", str(state_file), "probe", "profile_b"]) == 0
    assert cli.main(
        ["--state-file", str(state_file), "activate", "profile_b", "--confirm"]
    ) == 0
    assert profiles.load_profile_state(state_file)["active_profile"] == profiles.PROFILE_B

    assert cli.main(["--state-file", str(state_file), "probe", "profile_a"]) == 0
    assert cli.main(["--state-file", str(state_file), "failback", "--confirm"]) == 0
    assert profiles.load_profile_state(state_file)["active_profile"] == profiles.PROFILE_A


def test_operator_probe_rejects_unhealthy_b_and_records_cooldown(
    profile_config, capsys
):
    _, profile_b, state_file = profile_config
    profile_b.write_text(
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t4102444800\tVISITOR_INFO1_LIVE\tvisitor\n"
    )

    assert cli.main(["--state-file", str(state_file), "probe", "profile_b"]) == 2
    assert "anonymous_only" in capsys.readouterr().err
    state = profiles.load_profile_state(state_file)
    assert state["profiles"][profiles.PROFILE_B]["last_probe_ok"] is False
    assert state["profiles"][profiles.PROFILE_B]["cooldown_until"] is not None
    assert state["active_profile"] == profiles.PROFILE_A


def test_status_reports_absent_b_without_mutating_state(monkeypatch, tmp_path):
    profile_a = tmp_path / "profile-a.txt"
    state_file = tmp_path / "state.json"
    profile_a.write_text(_authenticated_cookie_text())
    monkeypatch.setattr(settings, "ytdlp_cookies_file", str(profile_a))
    monkeypatch.setattr(settings, "ytdlp_cookie_profile_b_file", "")
    monkeypatch.setattr(settings, "ytdlp_cookie_profile_state_file", str(state_file))

    payload = cli.status_payload(state_path=state_file)

    assert payload["active_profile"] == profiles.PROFILE_A
    assert payload["profiles"][profiles.PROFILE_B]["configured"] is False
    assert not state_file.exists()
