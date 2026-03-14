"""Integration-style tests for the full yt-transcribe workflow.

Mocks all HTTP (API) and email (gog CLI) interactions to exercise the
end-to-end flow through main() without network access.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import the module from its file path
_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "skills" / "yt-transcribe" / "scripts" / "process_and_email.py"
spec = importlib.util.spec_from_file_location("process_and_email", _SCRIPT_PATH)
mod = importlib.util.module_from_spec(spec)
sys.modules["process_and_email"] = mod
spec.loader.exec_module(mod)

main = mod.main
http_json = mod.http_json


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_VIDEO_ID = "test-uuid-1234"
_JOB_ID = "job-uuid-5678"

_SUBMIT_RESPONSE = {"job_id": _JOB_ID, "video_id": _VIDEO_ID}
_JOB_COMPLETED = {"status": "completed", "video_title": "Test Video Title"}
_TRANSCRIPTION = {
    "video_title": "Test Video Title",
    "summary": "## Key Points\nThis is a test summary.",
    "full_text": "Hello world, this is the full transcript.",
    "language_detected": "en",
    "speakers": ["SPEAKER_00"],
}

_CHANNEL_DISCOVERY = {
    "channel_name": "TestCreator",
    "videos": [
        {"url": "https://www.youtube.com/watch?v=vid1", "title": "Video One"},
        {"url": "https://www.youtube.com/watch?v=vid2", "title": "Video Two"},
    ],
}


def _mock_http_json(method: str, url: str, payload=None, **kwargs):
    """Route mocked HTTP calls based on URL pattern."""
    if "api/videos" in url and method == "POST":
        return dict(_SUBMIT_RESPONSE)
    if "api/jobs/" in url:
        return dict(_JOB_COMPLETED)
    if "api/transcriptions/" in url:
        return dict(_TRANSCRIPTION)
    if "api/channels" in url and method == "POST":
        return dict(_CHANNEL_DISCOVERY)
    if "oembed" in url:
        return {"title": "Fallback Title"}
    raise ValueError(f"Unmocked HTTP call: {method} {url}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestVideoWorkflowE2E:
    """Full end-to-end: single video URL → JSON output."""

    @patch.object(mod, "http_json", side_effect=_mock_http_json)
    def test_video_produces_valid_json(self, mock_http):
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            rc = main(["https://www.youtube.com/watch?v=abc123", "--to", "me", "--pretty"])

        assert rc == 0
        payload = json.loads(stdout.getvalue())

        assert payload["mode"] == "video"
        assert payload["recipient"] == "kenneth@01-digital.com"
        assert payload["sent"] is False
        assert "Youtube Transcript" in payload["subject"]
        assert len(payload["videos"]) == 1

        video = payload["videos"][0]
        assert video["status"] == "completed"
        assert video["summary"] is not None
        assert "Key Points" in video["summary"]
        assert video["transcript"] is None  # summary-only by default

    @patch.object(mod, "http_json", side_effect=_mock_http_json)
    def test_video_with_transcript(self, mock_http):
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            rc = main(["https://www.youtube.com/watch?v=abc123", "--to", "me", "--include-transcript", "--pretty"])

        assert rc == 0
        payload = json.loads(stdout.getvalue())
        video = payload["videos"][0]
        assert video["transcript"] is not None
        assert "full transcript" in video["transcript"].lower()

    @patch.object(mod, "http_json", side_effect=_mock_http_json)
    @patch.object(mod, "send_email")
    def test_video_with_send(self, mock_send, mock_http):
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            rc = main(["https://www.youtube.com/watch?v=abc123", "--to", "me", "--send", "--pretty"])

        assert rc == 0
        payload = json.loads(stdout.getvalue())
        assert payload["sent"] is True

        # Verify send_email was called correctly
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert call_args[0][0] == "kenneth@01-digital.com"  # recipient
        assert "Youtube Transcript" in call_args[0][1]  # subject
        assert isinstance(call_args[0][2], str)  # text body
        assert isinstance(call_args[0][3], str)  # html body

    @patch.object(mod, "http_json", side_effect=_mock_http_json)
    def test_html_body_in_output(self, mock_http):
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            rc = main(["https://www.youtube.com/watch?v=abc123", "--to", "me", "--pretty"])

        assert rc == 0
        payload = json.loads(stdout.getvalue())
        assert "html_body" in payload
        assert "YT Transcriber" in payload["html_body"]
        assert "Test Video Title" in payload["html_body"]


class TestChannelWorkflowE2E:
    """Full end-to-end: channel URL → JSON output."""

    @patch.object(mod, "http_json", side_effect=_mock_http_json)
    def test_channel_produces_digest(self, mock_http):
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            rc = main(["https://www.youtube.com/@TestCreator", "--to", "me", "--channel-limit", "2", "--pretty"])

        assert rc == 0
        payload = json.loads(stdout.getvalue())

        assert payload["mode"] == "channel"
        assert len(payload["videos"]) == 2
        assert "TestCreator" in payload["subject"]

    @patch.object(mod, "http_json", side_effect=lambda m, u, p=None, **kw: {
        "channel_name": "EmptyChannel", "videos": []
    } if "api/channels" in u else _mock_http_json(m, u, p, **kw))
    def test_empty_channel(self, mock_http):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            rc = main(["https://www.youtube.com/@EmptyChannel", "--to", "me", "--pretty"])

        assert rc == 0
        payload = json.loads(stdout.getvalue())
        assert payload["videos"] == []
        assert "No videos found" in payload["subject"]


class TestPlaylistRejection:
    """Playlist URLs should be cleanly rejected."""

    def test_pure_playlist_rejected(self):
        stderr = io.StringIO()
        stdout = io.StringIO()
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            rc = main(["https://www.youtube.com/playlist?list=PLxxxxx"])

        assert rc == 1
        err = stderr.getvalue()
        assert "Playlist URLs are not supported" in err
        assert "PLxxxxx" in err

    @patch.object(mod, "http_json", side_effect=_mock_http_json)
    def test_video_with_list_param_strips_list(self, mock_http):
        """A video URL with &list= should be treated as a single video (list stripped)."""
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            rc = main(["https://www.youtube.com/watch?v=abc123&list=PLxxx&index=5", "--pretty"])

        assert rc == 0
        payload = json.loads(stdout.getvalue())
        assert payload["mode"] == "video"
        # source_url should have list/index stripped
        assert "list=" not in payload["source_url"]
        assert "index=" not in payload["source_url"]
        assert "v=abc123" in payload["source_url"]


class TestNoUrlError:
    """Missing URL should produce a clear error."""

    def test_no_url_no_init(self):
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            rc = main([])

        assert rc == 1
        assert "url is required" in stderr.getvalue()


class TestInitRecipientsFlag:
    """--init-recipients should bootstrap the config file."""

    def test_init_recipients(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(Path, "home", return_value=Path(tmpdir)):
                stdout = io.StringIO()
                with patch("sys.stdout", stdout):
                    rc = main(["--init-recipients"])

                assert rc == 0
                assert "Created" in stdout.getvalue()

                config = Path(tmpdir) / ".yt-transcriber-recipients.json"
                assert config.is_file()
                data = json.loads(config.read_text())
                assert data["me"] == "kenneth@01-digital.com"
