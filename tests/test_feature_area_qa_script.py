from scripts.qa_feature_areas import Response, run_checks


VIDEO_ID = "11111111-1111-1111-1111-111111111111"
CHANNEL_ID = "22222222-2222-2222-2222-222222222222"
JOB_ID = "33333333-3333-3333-3333-333333333333"


def test_read_only_feature_matrix_covers_dynamic_surfaces_and_search():
    pages = {
        "/": f"Operations Hub /jobs/{JOB_ID}",
        "/queue": f"Processing Queue recent-jobs-body /jobs/{JOB_ID}",
        "/library?tab=videos": f'video-list-content /videos/{VIDEO_ID}',
        "/library?tab=channels": f'channel-card-wrapper /channels/{CHANNEL_ID}',
        "/chat": "chat-page-shell",
        "/search": "search-results",
        "/global-search": "global-search-results",
        "/partials/recent-jobs": "recent-jobs-body",
        f"/videos/{VIDEO_ID}": "page-title",
        f"/channels/{CHANNEL_ID}": "page-title",
        f"/channels/{CHANNEL_ID}/chat": 'id="chat-form"',
        f"/jobs/{JOB_ID}": "Job Details",
    }

    def fetch(path, method="GET", payload=None, follow=True, request_headers=None):
        if not follow and path == "/submit":
            return Response(302, "", {"Location": "/"})
        if not follow and path == "/channels":
            return Response(302, "", {"Location": "/library?tab=channels"})
        if path == "/queue" and request_headers == {"HX-Request": "true"}:
            return Response(200, "queue-summary", {})
        if path in pages:
            return Response(200, pages[path], {})
        if path == "/health":
            return Response(200, '{"status":"ok"}', {})
        if path in ("/api/chat/sessions", "/api/subscriptions", f"/api/agents/channel/{CHANNEL_ID}/sessions"):
            return Response(200, "[]", {})
        if path == "/api/llm/usage":
            return Response(200, '{"today_usd":0,"seven_day_usd":0}', {})
        if path == f"/api/videos/{VIDEO_ID}":
            return Response(200, f'{{"id":"{VIDEO_ID}","status":"completed"}}', {})
        if path == f"/api/transcriptions/{VIDEO_ID}":
            return Response(200, '{"language":"en","segments":[],"diarization_enabled":false}', {})
        if path == f"/api/channels/{CHANNEL_ID}/persona":
            return Response(200, '{"display_name":"Test"}', {})
        if path == f"/api/jobs/{JOB_ID}":
            return Response(200, f'{{"id":"{JOB_ID}","status":"completed"}}', {})
        if method == "POST" and path in ("/api/search", "/api/global-search"):
            return Response(200, '{"results":[]}', {})
        raise AssertionError(f"Unexpected request: {method} {path}")

    checks = run_checks(fetch)

    assert checks
    assert all(check.status == "pass" for check in checks), [check for check in checks if check.status != "pass"]
    assert {check.area for check in checks} >= {
        "Dashboard",
        "Queue",
        "Library / videos",
        "Library / channels",
        "Video detail",
        "Channel detail",
        "Channel persona chat",
        "Job detail",
        "Search API",
        "Global Search API",
    }
