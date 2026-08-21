from __future__ import annotations

import json
import socket
import urllib.request

from app.cli import ApiClient, CliError, build_parser, main


class _Client:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def request(self, method, path, *, query=None, body=None):
        self.calls.append((method, path, query, body))
        response = self.responses.pop(0) if self.responses else {}
        if isinstance(response, Exception):
            raise response
        return response


def test_status_json_calls_supported_system_endpoint(capsys):
    client = _Client([{"status": "ok", "warning_count": 2}])
    code = main(["--json", "status"], client=client)

    assert code == 0
    assert client.calls[0][0:2] == ("GET", "/api/system/status")
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


def test_jobs_passes_bounded_filter_contract():
    client = _Client([{"items": [], "total": 0, "limit": 10, "offset": 20}])
    code = main(["jobs", "--status", "failed", "--limit", "10", "--offset", "20"], client=client)

    assert code == 0
    _, path, query, _ = client.calls[0]
    assert path == "/api/jobs"
    assert query["status"] == "failed"
    assert query["limit"] == 10
    assert query["offset"] == 20


def test_submit_refuses_without_explicit_confirmation(capsys):
    client = _Client()
    code = main(["submit", "https://youtube.com/watch?v=abcdefghijk"], client=client)

    assert code == 2
    assert client.calls == []
    assert "without --confirm" in capsys.readouterr().err


def test_submit_keeps_service_url_separate_from_video_url():
    video_url = "https://youtube.com/watch?v=abcdefghijk"
    args = build_parser().parse_args(["--url", "http://127.0.0.1:8001", "submit", video_url, "--confirm"])
    client = _Client([{"status": "queued"}])

    assert args.base_url == "http://127.0.0.1:8001"
    assert args.video_url == video_url
    assert main(["submit", video_url, "--confirm"], client=client) == 0
    assert client.calls[0][3] == {"url": video_url}


def test_confirmed_retry_uses_api_mutation():
    client = _Client([{"status": "queued"}])
    code = main(["retry", "job-id", "--confirm"], client=client)

    assert code == 0
    assert client.calls[0][0:2] == ("POST", "/api/jobs/job-id/retry")


def test_manual_review_retry_override_is_explicit_and_confirmed():
    client = _Client([{"status": "queued", "manual_review_override": True}])

    code = main(
        ["retry", "job-id", "--override-manual-review", "--confirm"],
        client=client,
    )

    assert code == 0
    assert client.calls[0][2] == {"manual_review_override": "true"}


def test_reconcile_is_dry_run_by_default_and_apply_is_guarded(capsys):
    preview = _Client([{"mode": "dry_run", "items": [], "changed": 0}])
    assert main(["reconcile"], client=preview) == 0
    assert preview.calls[0][3] == {"apply": False}

    refused = _Client()
    assert main(["reconcile", "--apply"], client=refused) == 2
    assert refused.calls == []
    assert "without --confirm" in capsys.readouterr().err


def test_transport_errors_have_stable_nonzero_exit(capsys):
    client = _Client([CliError("API 503: unavailable")])
    assert main(["status"], client=client) == 2
    assert "API 503" in capsys.readouterr().err


def test_socket_timeout_becomes_stable_cli_error(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise socket.timeout("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", raise_timeout)

    client = ApiClient(timeout=12)
    try:
        client.request("GET", "/api/system/status")
    except CliError as exc:
        assert str(exc) == "Request to http://127.0.0.1:8000 timed out after 12 seconds"
    else:
        raise AssertionError("timeout was not converted to CliError")


def test_ask_uses_server_chat_router_and_returns_citations(capsys):
    client = _Client(
        [
            {"id": "session-1"},
            {
                "content": "Grounded answer",
                "sources": [{"video_title": "Talk", "start_time": 90}],
            },
        ]
    )

    assert main(["ask", "What mattered?", "--video-id", "video-1"], client=client) == 0
    assert client.calls[0][1] == "/api/chat/sessions"
    assert client.calls[1][1] == "/api/chat/sessions/session-1/messages"
    assert client.calls[1][3]["video_id"] == "video-1"
    output = capsys.readouterr().out
    assert "Grounded answer" in output
    assert "Talk @ 1:30" in output
