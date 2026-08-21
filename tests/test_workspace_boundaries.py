from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_template_rendering import MockDB, _build_client, _make_batch, _make_job


def _reader_video(*, title: str, channel, words: int = 900, summary: str | None = None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        youtube_video_id="reader123",
        title=title,
        thumbnail_url=None,
        duration_seconds=1800,
        status="completed",
        created_at=None,
        updated_at=None,
        channel_id=channel.id,
        channel=channel,
        transcription=SimpleNamespace(word_count=words),
        summary=SimpleNamespace(content=summary) if summary else None,
        report=SimpleNamespace(delivery_status="delivered"),
        chat_enabled=True,
    )


def _dashboard_db() -> MockDB:
    return MockDB(
        execute_1=[_make_job(status="completed")],
        execute_2=[_make_job(status="running", progress_pct=50)],
        execute_3=[_make_job(status="queued", progress_pct=0)],
        execute_4=[_make_job(status="completed")],
        execute_5=[],
        execute_6=[_make_batch()],
        scalar=0,
        default=[],
    )


def test_reader_home_is_the_default_workspace():
    response = _build_client(MockDB()).get("/")

    assert response.status_code == 200
    assert "Read what you saved, at your own pace" in response.text
    assert 'href="/static/css/reader.css?' in response.text
    assert "Transcript Reader" in response.text
    assert 'href="/ops"' in response.text
    assert 'id="video-form"' not in response.text


def test_reader_home_surfaces_continue_recent_and_later_without_queue_controls():
    channel = SimpleNamespace(id=uuid.uuid4(), name="Reader Channel")
    continuing = _reader_video(
        title="Continue this document",
        channel=channel,
        summary="A useful summary for returning readers.",
    )
    recent = _reader_video(title="Newly ready document", channel=channel, words=450)
    later = _reader_video(title="Saved for another day", channel=channel)
    continue_state = SimpleNamespace(video=continuing, progress_pct=42, status="reading")
    later_state = SimpleNamespace(video=later, progress_pct=0, status="later")
    db = MockDB(
        execute_1=[continue_state],
        execute_2=[(recent, None)],
        execute_3=[later_state],
        default=[],
        scalar=0,
    )

    response = _build_client(db).get("/")

    assert response.status_code == 200
    assert "Continue this document" in response.text
    assert "Newly ready document" in response.text
    assert "Saved for another day" in response.text
    assert "42 percent read" in response.text
    assert "4 min read" in response.text
    assert "Report ready" in response.text
    assert 'id="video-form"' not in response.text
    assert 'hx-post="/api/videos"' not in response.text


def test_reader_library_cards_and_pagination_preserve_filter_context():
    channel = SimpleNamespace(
        id=uuid.uuid4(),
        name="Focused Channel",
        thumbnail_url=None,
        chat_enabled=True,
    )
    video = _reader_video(
        title="Needle phrase document",
        channel=channel,
        summary="Summary preview is visible in the reading library.",
    )
    state = SimpleNamespace(video_id=video.id, progress_pct=35, status="later")
    db = MockDB(
        scalar=21,
        execute_1=[video],
        execute_2=[state],
        execute_3=[channel],
        execute_4=[(channel.id, 1)],
        default=[],
    )

    response = _build_client(db).get(
        f"/read?status=later&channel_id={channel.id}&sort=title&q=Needle%20phrase"
    )

    assert response.status_code == 200
    assert "Focused Channel" in response.text
    assert "Summary preview is visible" in response.text
    assert "4 min read" in response.text
    assert "Report ready" in response.text
    assert "35 percent read" in response.text
    assert f"channel_id={channel.id}" in response.text
    assert "q=Needle%20phrase" in response.text


def test_operations_overview_uses_its_own_layout_and_namespace():
    response = _build_client(_dashboard_db()).get("/ops")

    assert response.status_code == 200
    assert "Operations Hub" in response.text
    assert 'href="/static/css/operations.css?' in response.text
    assert "Transcript Operations" in response.text
    assert 'href="/ops/queue"' in response.text
    assert 'href="/" class="workspace-switch-link"' in response.text


def test_reader_library_and_static_video_list_do_not_conflict_with_video_ids():
    library_db = MockDB(scalar=0, execute_1=[], execute_2=[], execute_3=[], default=[])
    library_response = _build_client(library_db).get("/read")
    video_list_response = _build_client(MockDB(scalar=0, execute_1=[], default=[])).get(
        "/read/videos"
    )

    assert library_response.status_code == 200
    assert "Library" in library_response.text
    assert video_list_response.status_code == 200
    assert "Videos" in video_list_response.text


@pytest.mark.parametrize(
    ("legacy_path", "canonical_location"),
    [
        ("/submit?source=bookmark", "/ops?source=bookmark#submit-video"),
        ("/queue?view=failed", "/ops/queue?view=failed"),
        ("/library?tab=channels&page=2", "/read?tab=channels&page=2"),
        ("/videos?page=3", "/read/videos?page=3"),
        ("/channels", "/read?tab=channels"),
    ],
)
def test_legacy_collection_routes_redirect_and_preserve_queries(
    legacy_path: str,
    canonical_location: str,
):
    response = _build_client(MockDB()).get(legacy_path, follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == canonical_location


@pytest.mark.parametrize(
    ("legacy_path", "canonical_location"),
    [
        ("/videos/{id}", "/read/{id}"),
        ("/channels/{id}", "/read/channels/{id}"),
        ("/channels/{id}/chat", "/read/channels/{id}/chat"),
        ("/jobs/{id}", "/ops/jobs/{id}"),
    ],
)
def test_legacy_detail_routes_redirect_to_the_owning_workspace(
    legacy_path: str,
    canonical_location: str,
):
    entity_id = str(uuid.uuid4())
    response = _build_client(MockDB()).get(
        legacy_path.format(id=entity_id),
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == canonical_location.format(id=entity_id)


@pytest.mark.parametrize("path", ["/", "/read", "/search", "/chat", "/ops", "/ops/queue"])
def test_workspace_pages_expose_skip_navigation(path: str):
    if path == "/ops":
        db = _dashboard_db()
    elif path == "/ops/queue":
        db = MockDB(default=[], scalar=0)
    else:
        db = MockDB(default=[], scalar=0)

    response = _build_client(db).get(path)

    assert response.status_code == 200
    assert 'class="skip-link"' in response.text
    assert 'href="#main-content"' in response.text
    assert 'id="main-content"' in response.text


def test_mobile_navigation_has_state_and_44px_target_contract():
    reader_html = _build_client(MockDB()).get("/").text
    operations_html = _build_client(_dashboard_db()).get("/ops").text
    css = Path("app/static/css/main.css").read_text(encoding="utf-8")

    assert 'aria-controls="reader-mobile-nav"' in reader_html
    assert 'aria-controls="operations-mobile-nav"' in operations_html
    assert 'aria-expanded="false"' in reader_html
    assert 'aria-expanded="false"' in operations_html
    assert "min-height: 2.75rem" in css


def test_mobile_chat_composer_and_tablet_pagination_keep_44px_targets():
    main_css = Path("app/static/css/main.css").read_text(encoding="utf-8")
    reader_css = Path("app/static/css/reader.css").read_text(encoding="utf-8")

    assert "#chat-channel-filter:disabled { display: none; }" in main_css
    assert "grid-template-columns: minmax(0, 1fr) 2.75rem" in main_css
    assert "height: calc(100dvh - 8.75rem)" in main_css
    assert ".workspace-reader .page-btn { min-width: 2.75rem; height: 2.75rem; }" in reader_css


def test_api_routes_keep_their_existing_paths():
    client = _build_client(MockDB())
    paths = {
        getattr(route, "path", None)
        for route in client.app.routes
        if getattr(route, "path", None) is not None
    }

    assert "/api/videos" in paths
    assert "/api/jobs/{job_id}" in paths
    assert "/api/subscriptions" in paths
    assert "/api/operations/summary" in paths
