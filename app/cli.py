from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Sequence


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 180.0


class CliError(RuntimeError):
    pass


@dataclass
class ApiClient:
    base_url: str = DEFAULT_BASE_URL
    actor: str = "cli"
    api_key: str | None = None
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        url = self.base_url.rstrip("/") + path
        if query:
            encoded = urllib.parse.urlencode(
                {key: value for key, value in query.items() if value is not None},
                doseq=True,
            )
            if encoded:
                url += "?" + encoded
        headers = {"Accept": "application/json", "X-YT-Actor": self.actor}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw).get("detail", raw)
            except json.JSONDecodeError:
                detail = raw
            raise CliError(f"API {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise CliError(f"Could not reach {self.base_url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise CliError(
                f"Request to {self.base_url} timed out after {self.timeout:g} seconds"
            ) from exc
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CliError("Service returned non-JSON output") from exc


def _require_confirm(args: argparse.Namespace, action: str) -> None:
    if not getattr(args, "confirm", False):
        raise CliError(f"Refusing to {action} without --confirm")


def _add_page_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ytctl", description="Local YouTube Transcriber control client")
    parser.add_argument(
        "--url",
        dest="base_url",
        default=os.getenv("YT_TRANSCRIBER_URL", DEFAULT_BASE_URL),
    )
    parser.add_argument("--api-key", default=os.getenv("YT_TRANSCRIBER_API_KEY"))
    parser.add_argument("--actor", default=os.getenv("YT_TRANSCRIBER_ACTOR", "cli"))
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("YT_TRANSCRIBER_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)),
        help="Request timeout in seconds (default: 180)",
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("status", help="Show service, queue, and warning status")
    commands.add_parser("workers", help="Show worker queue coverage")
    commands.add_parser("warnings", help="Show actionable operational warnings")

    jobs = commands.add_parser("jobs", help="List jobs")
    jobs.add_argument("--status")
    jobs.add_argument("--stage")
    jobs.add_argument("--channel-id")
    jobs.add_argument("--video-id")
    jobs.add_argument("--include-hidden", action="store_true")
    _add_page_args(jobs)
    job = commands.add_parser("job", help="Inspect one job")
    job.add_argument("job_id")

    videos = commands.add_parser("videos", help="List videos")
    videos.add_argument("--status")
    videos.add_argument("--channel-id")
    videos.add_argument("--reader-status")
    videos.add_argument("--query", dest="q")
    videos.add_argument("--include-dismissed", action="store_true")
    _add_page_args(videos)

    transcript = commands.add_parser("transcript", help="Read a transcript and summary")
    transcript.add_argument("video_id")
    transcript.add_argument("--summary-only", action="store_true")

    reader = commands.add_parser("reader", help="List saved Reader state")
    reader.add_argument("--status")
    _add_page_args(reader)

    search = commands.add_parser("search", help="Search across the transcript library")
    search.add_argument("query")
    search.add_argument("--video-id")
    search.add_argument("--channel-id")
    search.add_argument("--source-type", default="all")
    search.add_argument("--limit", type=int, default=10)

    ask = commands.add_parser("ask", help="Ask through the service's scoped RAG chat")
    ask.add_argument("question")
    ask.add_argument("--video-id")
    ask.add_argument("--channel-id")
    ask.add_argument("--session-id")

    commands.add_parser("subscriptions", help="List channel subscriptions")

    submit = commands.add_parser("submit", help="Submit one video")
    submit.add_argument("video_url")
    submit.add_argument("--confirm", action="store_true")
    retry = commands.add_parser("retry", help="Retry a failed job")
    retry.add_argument("job_id")
    retry.add_argument("--confirm", action="store_true")
    cancel = commands.add_parser("cancel", help="Cancel a pending job")
    cancel.add_argument("job_id")
    cancel.add_argument("--confirm", action="store_true")
    reconcile = commands.add_parser("reconcile", help="Preview or apply stale batch reconciliation")
    reconcile.add_argument("--apply", action="store_true")
    reconcile.add_argument("--confirm", action="store_true")
    return parser


def _dispatch(client: ApiClient, args: argparse.Namespace) -> Any:
    command = args.command
    if command == "status":
        return client.request("GET", "/api/system/status")
    if command == "workers":
        return client.request("GET", "/api/system/status")["queue_health"]
    if command == "warnings":
        payload = client.request("GET", "/api/operations/summary")
        return {"warning_count": payload["warning_count"], "items": payload["warnings"]}
    if command == "jobs":
        return client.request(
            "GET",
            "/api/jobs",
            query={
                "status": args.status,
                "stage": args.stage,
                "channel_id": args.channel_id,
                "video_id": args.video_id,
                "include_hidden": str(args.include_hidden).lower(),
                "limit": args.limit,
                "offset": args.offset,
            },
        )
    if command == "job":
        return client.request("GET", f"/api/jobs/{args.job_id}")
    if command == "videos":
        return client.request(
            "GET",
            "/api/videos",
            query={
                "status": args.status,
                "channel_id": args.channel_id,
                "reader_status": args.reader_status,
                "q": args.q,
                "include_dismissed": str(args.include_dismissed).lower(),
                "limit": args.limit,
                "offset": args.offset,
            },
        )
    if command == "transcript":
        payload = client.request("GET", f"/api/transcriptions/{args.video_id}")
        if args.summary_only:
            return {"video_id": payload["video_id"], "summary": payload.get("summary")}
        return payload
    if command == "reader":
        return client.request(
            "GET",
            "/api/reader/states",
            query={"status": args.status, "limit": args.limit, "offset": args.offset},
        )
    if command == "search":
        return client.request(
            "POST",
            "/api/global-search",
            body={
                "query": args.query,
                "video_id": args.video_id,
                "channel_id": args.channel_id,
                "source_type": args.source_type,
                "limit": args.limit,
            },
        )
    if command == "ask":
        session_id = args.session_id
        if not session_id:
            session = client.request(
                "POST",
                "/api/chat/sessions",
                body={"title": args.question[:80], "platform": args.actor},
            )
            session_id = session["id"]
        message = client.request(
            "POST",
            f"/api/chat/sessions/{session_id}/messages",
            body={
                "content": args.question,
                "video_id": args.video_id,
                "channel_id": args.channel_id,
            },
        )
        return {"session_id": session_id, **message}
    if command == "subscriptions":
        return client.request("GET", "/api/subscriptions")
    if command == "submit":
        _require_confirm(args, "submit a video")
        return client.request("POST", "/api/videos", body={"url": args.video_url})
    if command == "retry":
        _require_confirm(args, "retry a job")
        return client.request("POST", f"/api/jobs/{args.job_id}/retry")
    if command == "cancel":
        _require_confirm(args, "cancel a job")
        return client.request("POST", f"/api/jobs/{args.job_id}/cancel")
    if command == "reconcile":
        if args.apply:
            _require_confirm(args, "apply batch reconciliation")
        return client.request("POST", "/api/operations/reconcile-batches", body={"apply": args.apply})
    raise CliError(f"Unknown command: {command}")


def _human_text(command: str, payload: Any) -> str:
    if command == "ask" and isinstance(payload, dict):
        sources = payload.get("sources") or []
        lines = [payload.get("content", "")]
        if sources:
            lines.append("\nSources")
            for source in sources:
                timestamp = source.get("start_time")
                location = f" @ {int(timestamp // 60)}:{int(timestamp % 60):02d}" if timestamp is not None else ""
                lines.append(f"- {source.get('video_title')}{location}")
        return "\n".join(lines).strip()
    if command == "transcript" and isinstance(payload, dict) and payload.get("full_text"):
        summary = payload.get("summary")
        return ((f"Summary\n-------\n{summary}\n\n" if summary else "") + payload["full_text"]).strip()
    if command == "warnings" and isinstance(payload, dict):
        items = payload.get("items", [])
        if not items:
            return "No operational warnings."
        lines = [f"{payload.get('warning_count', len(items))} operational warning(s)"]
        for item in items:
            lines.append(
                f"- [{item.get('warning_type')}] {item.get('title')}: {item.get('detail')} Next: {item.get('next_action')}"
            )
        return "\n".join(lines)
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        lines = [f"{payload.get('total', len(payload['items']))} total"]
        for item in payload["items"]:
            title = item.get("video_title") or item.get("title") or item.get("id")
            state = item.get("status") or item.get("warning_type") or ""
            lines.append(f"- {title} {state}".rstrip())
        return "\n".join(lines)
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def main(argv: Sequence[str] | None = None, *, client: ApiClient | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    resolved_client = client or ApiClient(
        args.base_url,
        actor=args.actor,
        api_key=args.api_key,
        timeout=args.timeout,
    )
    try:
        payload = _dispatch(resolved_client, args)
    except CliError as exc:
        print(f"ytctl: {exc}", file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    else:
        print(_human_text(args.command, payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
