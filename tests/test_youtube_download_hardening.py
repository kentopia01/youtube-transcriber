from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid

from app.models.job import Job
from app.services import youtube_download_hardening as mod


def test_cookie_lint_marks_anonymous_only_cookie_file(tmp_path):
    cookie_file = tmp_path / "youtube.txt"
    future = int((datetime.now(UTC) + timedelta(days=30)).timestamp())
    cookie_file.write_text(
        "\n".join(
            [
                "# Netscape HTTP Cookie File",
                f".youtube.com\tTRUE\t/\tTRUE\t{future}\tVISITOR_INFO1_LIVE\tabc",
                ".youtube.com\tTRUE\t/\tTRUE\t0\tYSC\tdef",
            ]
        )
    )

    health = mod.inspect_cookie_file(cookie_file)

    assert health.exists is True
    assert health.readable is True
    assert health.cookie_count == 2
    assert health.auth_cookie_count == 0
    assert health.status == "anonymous_only"
    assert "no_auth_like_youtube_cookies" in health.warnings


def test_cookie_lint_detects_auth_like_youtube_cookie(tmp_path):
    cookie_file = tmp_path / "youtube.txt"
    future = int((datetime.now(UTC) + timedelta(days=30)).timestamp())
    cookie_file.write_text(
        f".youtube.com\tTRUE\t/\tTRUE\t{future}\t__Secure-3PSID\tsecret\n"
    )

    health = mod.inspect_cookie_file(cookie_file)

    assert health.auth_cookie_count == 1
    assert health.status == "ok"


def test_cookie_lint_counts_httponly_auth_cookie(tmp_path):
    cookie_file = tmp_path / "youtube.txt"
    cookie_file.write_text(
        "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t4102444800\t__Secure-3PSID\tsecret\n"
    )

    health = mod.inspect_cookie_file(cookie_file)

    assert health.auth_cookie_count == 1
    assert health.status == "ok"


def test_media_probe_enables_official_ejs_solver(tmp_path):
    opts = mod._probe_opts(cookie_path=None, output_dir=tmp_path, test_download=True)

    assert opts["remote_components"] == ["ejs:github"]


def test_download_403_failure_classifier_matches_signature():
    job = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        job_type="pipeline",
        status="failed",
        current_stage="download",
        failure_signature="download|DownloadError|error: unable to download video data: http error #: forbidden",
        error_message="ERROR: unable to download video data: HTTP Error 403: Forbidden",
    )

    assert mod.is_download_403_failure(job) is True


def test_download_403_failure_classifier_rejects_other_stages():
    job = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        job_type="pipeline",
        status="failed",
        current_stage="summarize",
        failure_signature="summarize|DownloadError|http error #: forbidden",
    )

    assert mod.is_download_403_failure(job) is False


def test_download_access_classifier_matches_final_antibot_message():
    job = Job(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        job_type="pipeline",
        status="failed",
        current_stage="download",
        failure_signature="download|DownloadError|sign in to confirm you’re not a bot",
        error_message="ERROR: [youtube] abc: Sign in to confirm you’re not a bot",
    )

    assert mod.is_download_access_degradation_failure(job) is True


def test_ytdlp_version_health_flags_old_versions(monkeypatch):
    monkeypatch.setattr(mod.yt_dlp.version, "__version__", "2026.03.03")
    now = datetime(2026, 6, 19, tzinfo=UTC)

    health = mod.get_ytdlp_version_health(warn_days=75, now=now)

    assert health.version == "2026.03.03"
    assert health.age_days == 108
    assert health.status == "old"
