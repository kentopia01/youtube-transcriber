#!/usr/bin/env python3
"""Read-only live QA for Reader, Operations, and shared GET/search surfaces."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Callable

UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


@dataclass(frozen=True)
class Response:
    status: int
    body: str
    headers: dict[str, str]


@dataclass(frozen=True)
class Check:
    area: str
    target: str
    status: str
    detail: str


Fetch = Callable[[str, str, dict | None, bool, dict[str, str] | None], Response]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def http_fetcher(base_url: str, api_key: str | None, timeout: float) -> Fetch:
    normal = urllib.request.build_opener()
    no_redirect = urllib.request.build_opener(NoRedirect)

    def fetch(
        path: str,
        method: str = "GET",
        payload: dict | None = None,
        follow: bool = True,
        request_headers: dict[str, str] | None = None,
    ) -> Response:
        headers = dict(request_headers or {})
        data = None
        if api_key:
            headers["X-API-Key"] = api_key
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(base_url.rstrip("/") + path, data=data, headers=headers, method=method)
        opener = normal if follow else no_redirect
        try:
            with opener.open(request, timeout=timeout) as response:
                return Response(response.status, response.read().decode("utf-8"), dict(response.headers))
        except urllib.error.HTTPError as exc:
            return Response(exc.code, exc.read().decode("utf-8"), dict(exc.headers))

    return fetch


def _check_page(fetch: Fetch, area: str, path: str, marker: str) -> tuple[Check, Response]:
    try:
        response = fetch(path, "GET", None, True, None)
        ok = response.status == 200 and marker in response.body
        detail = f"HTTP {response.status}; marker {'found' if marker in response.body else 'missing'}"
        return Check(area, path, "pass" if ok else "fail", detail), response
    except Exception as exc:  # noqa: BLE001 - QA must report every area
        return Check(area, path, "fail", f"{exc.__class__.__name__}: {exc}"), Response(0, "", {})


def _check_json(fetch: Fetch, area: str, path: str, *, keys: tuple[str, ...] = ()) -> Check:
    try:
        response = fetch(path, "GET", None, True, None)
        value = json.loads(response.body) if response.body else None
        ok = response.status == 200 and all(isinstance(value, dict) and key in value for key in keys)
        if not keys:
            ok = response.status == 200 and isinstance(value, (dict, list))
        return Check(area, path, "pass" if ok else "fail", f"HTTP {response.status}; JSON {type(value).__name__}")
    except Exception as exc:  # noqa: BLE001
        return Check(area, path, "fail", f"{exc.__class__.__name__}: {exc}")


def _ids(body: str, path_prefix: str) -> list[str]:
    return list(dict.fromkeys(re.findall(rf'{re.escape(path_prefix)}/({UUID_PATTERN})', body)))


def run_checks(fetch: Fetch) -> list[Check]:
    checks: list[Check] = []
    page_specs = (
        ("Reader home", "/", "Read what you saved"),
        ("Operations dashboard", "/ops", "Operations Hub"),
        ("Queue", "/ops/queue", "Processing Queue"),
        ("Library / videos", "/read?tab=videos", "video-list-content"),
        ("Library / channels", "/read?tab=channels", "channel-card-wrapper"),
        ("Chat", "/chat", "chat-page-shell"),
        ("Research", "/search", "search-results"),
        ("Highlights notebook", "/read/highlights", "Highlights and notes"),
    )
    responses: dict[str, Response] = {}
    for area, path, marker in page_specs:
        check, response = _check_page(fetch, area, path, marker)
        checks.append(check)
        responses[path] = response

    for area, path, location in (
        ("Legacy submit redirect", "/submit", "/ops#submit-video"),
        ("Legacy queue redirect", "/queue", "/ops/queue"),
        ("Legacy library redirect", "/library?tab=videos", "/read?tab=videos"),
        ("Legacy channels redirect", "/channels", "/read?tab=channels"),
        ("Legacy global search redirect", "/global-search", "/search"),
    ):
        response = fetch(path, "GET", None, False, None)
        actual = response.headers.get("Location") or response.headers.get("location", "")
        checks.append(Check(area, path, "pass" if response.status == 307 and actual == location else "fail", f"HTTP {response.status}; location={actual}"))

    checks.append(_check_page(fetch, "Recent jobs partial", "/ops/partials/recent-jobs", "recent-jobs-body")[0])
    partial = fetch("/ops/queue", "GET", None, True, {"HX-Request": "true"})
    partial_ok = partial.status == 200 and "queue-summary" in partial.body and "<html" not in partial.body
    checks.append(Check("Queue HTMX partial", "/ops/queue [HX-Request]", "pass" if partial_ok else "fail", f"HTTP {partial.status}; partial={partial_ok}"))

    checks.extend([
        _check_json(fetch, "Health API", "/health", keys=("status",)),
        _check_json(fetch, "Chat sessions API", "/api/chat/sessions"),
        _check_json(fetch, "Subscriptions API", "/api/subscriptions"),
        _check_json(fetch, "LLM usage API", "/api/llm/usage", keys=("today_usd", "seven_day_usd")),
    ])

    library_body = responses["/read?tab=videos"].body + responses["/read?tab=channels"].body
    video_ids = _ids(library_body, "/read")
    channel_ids = _ids(library_body, "/read/channels")
    job_ids = _ids(responses["/ops/queue"].body + responses["/ops"].body, "/ops/jobs")

    if video_ids:
        video_id = video_ids[0]
        checks.append(
            _check_page(
                fetch,
                "Video detail",
                f"/read/{video_id}",
                'id="reader-document"',
            )[0]
        )
        checks.append(_check_json(fetch, "Video API", f"/api/videos/{video_id}", keys=("id", "status")))
        checks.append(_check_json(fetch, "Reader annotations API", f"/api/reader/videos/{video_id}/annotations"))
        checks.append(_check_json(fetch, "Reader chapters API", f"/api/reader/videos/{video_id}/chapters", keys=("chapters", "provenance")))
        checks.append(_check_page(fetch, "Current transcript research scope", f"/search?video_id={video_id}", "Current transcript")[0])
        transcription_ok = False
        transcription_detail = "No rendered video had a transcription response"
        for candidate in video_ids[:20]:
            response = fetch(f"/api/transcriptions/{candidate}", "GET", None, True, None)
            if response.status == 200:
                value = json.loads(response.body)
                transcription_ok = all(key in value for key in ("language", "segments", "diarization_enabled"))
                transcription_detail = f"HTTP 200 using {candidate}"
                break
        checks.append(Check("Transcription API", "/api/transcriptions/{video_id}", "pass" if transcription_ok else "fail", transcription_detail))
    else:
        checks.append(Check("Video detail/API", "/read/{video_id}", "fail", "No video IDs discovered"))

    if channel_ids:
        channel_id = channel_ids[0]
        checks.append(_check_page(fetch, "Channel detail", f"/read/channels/{channel_id}", "page-title")[0])
        persona_channel = None
        for candidate in channel_ids[:30]:
            response = fetch(f"/api/channels/{candidate}/persona", "GET", None, True, None)
            if response.status == 200:
                persona_channel = candidate
                break
        if persona_channel:
            checks.append(_check_json(fetch, "Channel persona API", f"/api/channels/{persona_channel}/persona"))
            checks.append(_check_page(fetch, "Channel persona chat", f"/read/channels/{persona_channel}/chat", 'id="chat-form"')[0])
            checks.append(_check_json(fetch, "Channel agent sessions", f"/api/agents/channel/{persona_channel}/sessions"))
        else:
            checks.append(Check("Channel persona surfaces", "/api/channels/{channel_id}/persona", "fail", "No channel with a generated persona discovered"))
    else:
        checks.append(Check("Channel detail/API", "/read/channels/{channel_id}", "fail", "No channel IDs discovered"))

    if job_ids:
        job_id = job_ids[0]
        checks.append(_check_page(fetch, "Job detail", f"/ops/jobs/{job_id}", "Job Details")[0])
        checks.append(_check_json(fetch, "Job API", f"/api/jobs/{job_id}", keys=("id", "status")))
    else:
        checks.append(Check("Job detail/API", "/ops/jobs/{job_id}", "fail", "No job IDs discovered"))

    for area, path in (("Search API", "/api/search"), ("Global Search API", "/api/global-search")):
        try:
            response = fetch(path, "POST", {"query": "AI agents", "limit": 3}, True, None)
            value = json.loads(response.body)
            ok = response.status == 200 and isinstance(value.get("results"), list)
            checks.append(Check(area, path, "pass" if ok else "fail", f"HTTP {response.status}; results={len(value.get('results', []))}"))
        except Exception as exc:  # noqa: BLE001
            checks.append(Check(area, path, "fail", f"{exc.__class__.__name__}: {exc}"))

    return checks


def render_markdown(checks: list[Check]) -> str:
    lines = ["| Feature area | Target | Result | Detail |", "|---|---|---:|---|"]
    for check in checks:
        detail = check.detail.replace("|", "\\|")
        lines.append(f"| {check.area} | `{check.target}` | {check.status.upper()} | {detail} |")
    passed = sum(check.status == "pass" for check in checks)
    lines.extend(["", f"Result: **{passed}/{len(checks)} passed**."])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default=os.environ.get("API_KEY"))
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    checks = run_checks(http_fetcher(args.base_url, args.api_key, args.timeout))
    print(json.dumps([asdict(check) for check in checks], indent=2) if args.json else render_markdown(checks))
    return 1 if any(check.status == "fail" for check in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
