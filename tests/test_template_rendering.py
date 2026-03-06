"""Tests that every page template renders without errors under the new design system.

All page routes are tested with a mock DB to verify:
1. HTTP 200 status for each page
2. Key structural elements of the new design (top-nav, Iconoir, design tokens)
3. No daisyUI remnants in rendered output
4. HTMX attributes are present where expected
5. Correct Jinja2 variable interpolation
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.dependencies import get_db
from app.main import create_app

# ---------------------------------------------------------------------------
# Fake DB layer
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_job(**overrides):
    video = SimpleNamespace(title="Test Video Title")
    defaults = dict(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        channel_id=None,
        batch_id=None,
        celery_task_id="celery-abc",
        job_type="pipeline",
        status="completed",
        progress_pct=100.0,
        progress_message="Done",
        error_message=None,
        started_at=_NOW,
        completed_at=_NOW,
        created_at=_NOW,
        video=video,
    )
    defaults.update(overrides)
    obj = SimpleNamespace(**defaults)
    # Add display_name property behavior
    if obj.video and obj.video.title:
        title = obj.video.title
        obj.display_name = title[:60] + ("..." if len(title) > 60 else "")
    else:
        obj.display_name = obj.job_type
    return obj


def _make_video(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        youtube_video_id="dQw4w9WgXcQ",
        channel_id=None,
        title="Test Video Title",
        description="A test video description",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        duration_seconds=180.0,
        published_at=_NOW,
        thumbnail_url="https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        audio_file_path=None,
        status="completed",
        error_message=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_channel(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        youtube_channel_id="UC_channel_id",
        name="Test Channel",
        url="https://www.youtube.com/@testchannel",
        description="A test channel",
        thumbnail_url="https://yt3.ggpht.com/thumb.jpg",
        video_count=5,
        last_synced_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_batch(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        batch_number=1,
        total_batches=2,
        total_videos=5,
        completed_videos=3,
        failed_videos=0,
        status="running",
        created_at=_NOW,
        completed_at=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_transcription(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        full_text="This is the full transcript text of the video.",
        language="en",
        model_size="base",
        word_count=150,
        processing_time_seconds=12.5,
        created_at=_NOW,
        segments=[],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_segment(idx=0, **overrides):
    defaults = dict(
        segment_index=idx,
        start_time=idx * 5.0,
        end_time=(idx + 1) * 5.0,
        text=f"Segment {idx} text content.",
        confidence=0.95,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_summary(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        content="This is a summary of the video content.",
        model="claude-sonnet-4-20250514",
        prompt_tokens=500,
        completion_tokens=200,
        created_at=_NOW,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class _FakeScalarsResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        if isinstance(self._value, list):
            return _FakeScalarsResult(self._value)
        return _FakeScalarsResult([self._value] if self._value else [])


class MockDB:
    """A mock async DB that returns predictable data for page rendering."""

    def __init__(self, **kwargs):
        self._data = kwargs
        self._execute_count = 0

    async def execute(self, *args, **kwargs):
        self._execute_count += 1
        key = f"execute_{self._execute_count}"
        if key in self._data:
            return _FakeResult(self._data[key])
        return _FakeResult(self._data.get("default", []))

    async def scalar(self, *args, **kwargs):
        return self._data.get("scalar", 0)

    async def commit(self):
        pass

    async def flush(self):
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DAISY_PATTERNS = [
    "badge-success", "badge-error", "badge-warning", "badge-info", "badge-ghost",
    "card-title", "drawer-content", "drawer-side", "modal-box",
    "collapse-arrow", "table-zebra", "tabs-bordered", "tab-active",
    "bg-base-100", "text-base-content", "daisyui",
]

NEW_DESIGN_MARKERS = [
    "top-nav",          # New nav layout
    "Playfair Display", # Headline font
    "JetBrains Mono",   # Mono font
    "iconoir",          # Icon system
    "htmx.org@2.0.4",  # HTMX preserved
]


def _assert_no_daisyui(html: str):
    for pattern in DAISY_PATTERNS:
        assert pattern not in html, f"Found daisyUI remnant: {pattern}"


def _assert_new_design(html: str):
    for marker in NEW_DESIGN_MARKERS:
        assert marker in html, f"Missing new design marker: {marker}"


def _build_client(db_override=None):
    app = create_app()

    async def _override():
        yield db_override or MockDB()

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests: Base layout
# ---------------------------------------------------------------------------


class TestBaseLayout:
    def test_base_has_top_nav(self):
        client = _build_client(MockDB(scalar=0, default=[]))
        resp = client.get("/search")
        assert resp.status_code == 200
        html = resp.text
        assert '<nav class="top-nav">' in html
        assert "nav-brand" in html
        assert "YT Transcriber" in html

    def test_base_has_iconoir_cdn(self):
        client = _build_client(MockDB(scalar=0, default=[]))
        resp = client.get("/search")
        assert "iconoir" in resp.text

    def test_base_has_new_fonts(self):
        client = _build_client(MockDB(scalar=0, default=[]))
        resp = client.get("/search")
        html = resp.text
        assert "Playfair+Display" in html
        assert "Inter" in html
        assert "JetBrains+Mono" in html

    def test_base_has_no_daisyui_cdn(self):
        client = _build_client(MockDB(scalar=0, default=[]))
        resp = client.get("/search")
        assert "daisyui" not in resp.text

    def test_base_has_footer(self):
        client = _build_client(MockDB(scalar=0, default=[]))
        resp = client.get("/search")
        assert "Powered by faster-whisper" in resp.text

    def test_nav_links_present(self):
        client = _build_client(MockDB(scalar=0, default=[]))
        resp = client.get("/search")
        html = resp.text
        assert 'href="/"' in html
        assert 'href="/queue"' in html
        assert 'href="/library"' in html
        assert 'href="/chat"' in html
        assert 'href="/videos"' not in html
        assert 'href="/channels"' not in html
        assert "Chat with Library" in html

    def test_search_nav_active_state(self):
        client = _build_client(MockDB(scalar=0, default=[]))
        resp = client.get("/search")
        # The search page doesn't mark any nav-link as active (it's an action button)
        # but the page should still render fine
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: Dashboard (index.html)
# ---------------------------------------------------------------------------


class TestDashboardPage:
    def _build_dashboard_db(self):
        jobs = [
            _make_job(status="completed"),
            _make_job(status="running", progress_pct=50),
        ]
        active_jobs = [_make_job(status="running", progress_pct=50)]
        pending_jobs = [_make_job(status="queued", progress_pct=0)]
        completed_jobs = [_make_job(status="completed")]
        failed_jobs = [_make_job(status="failed", error_message="Download error")]
        active_batches = [_make_batch()]
        return MockDB(
            execute_1=jobs,           # recent jobs
            execute_2=active_jobs,    # active jobs
            scalar=3,                 # counts (total_videos, completed, channels)
            execute_3=pending_jobs,
            execute_4=completed_jobs,
            execute_5=failed_jobs,
            execute_6=active_batches,
            default=[],
        )

    def test_dashboard_renders(self):
        client = _build_client(self._build_dashboard_db())
        resp = client.get("/")
        assert resp.status_code == 200

    def test_dashboard_has_hero(self):
        client = _build_client(self._build_dashboard_db())
        resp = client.get("/")
        html = resp.text
        assert "Operations Hub" in html
        assert "Transcribe videos without babysitting jobs" in html
        assert "bracket-accent" in html

    def test_dashboard_has_stat_cards(self):
        client = _build_client(self._build_dashboard_db())
        resp = client.get("/")
        html = resp.text
        assert "stat-card" in html
        assert "Total Videos" in html
        assert "Completed" in html
        assert "Channels" in html
        assert "Active Jobs" in html

    def test_dashboard_has_video_form(self):
        client = _build_client(self._build_dashboard_db())
        resp = client.get("/")
        html = resp.text
        assert 'id="video-form"' in html
        assert 'id="video-url"' in html
        assert "Start Transcription Job" in html

    def test_dashboard_has_channel_form(self):
        client = _build_client(self._build_dashboard_db())
        resp = client.get("/")
        html = resp.text
        assert 'id="channel-form"' in html
        assert 'id="channel-url"' in html

    def test_dashboard_has_queue_polling(self):
        client = _build_client(self._build_dashboard_db())
        resp = client.get("/")
        html = resp.text
        assert 'hx-get="/queue"' in html
        assert 'hx-target="#queue-content"' in html

    def test_dashboard_has_jobs_table(self):
        client = _build_client(self._build_dashboard_db())
        resp = client.get("/")
        html = resp.text
        assert "Recent Jobs" in html
        assert "data-table" in html

    def test_dashboard_has_recent_jobs_polling(self):
        client = _build_client(self._build_dashboard_db())
        resp = client.get("/")
        html = resp.text
        assert 'id="recent-jobs-body"' in html
        assert 'hx-get="/partials/recent-jobs"' in html
        assert 'hx-trigger="load delay:5s"' in html

    def test_dashboard_has_chat_launcher(self):
        client = _build_client(self._build_dashboard_db())
        resp = client.get("/")
        html = resp.text
        assert "Chat with Library" in html
        assert 'id="quick-search-form"' in html
        assert 'id="quick-search-input"' in html
        assert "Ask a question about your videos" in html

    def test_recent_jobs_partial_endpoint(self):
        db = MockDB(execute_1=[_make_job(status="completed")], default=[])
        client = _build_client(db)
        resp = client.get("/partials/recent-jobs")
        assert resp.status_code == 200
        html = resp.text
        assert "Test Video Title" in html
        assert '<html' not in html

    def test_dashboard_has_modal(self):
        client = _build_client(self._build_dashboard_db())
        resp = client.get("/")
        html = resp.text
        assert 'id="channel-confirm-dialog"' in html
        assert "modal-dialog" in html

    def test_dashboard_no_daisyui(self):
        client = _build_client(self._build_dashboard_db())
        resp = client.get("/")
        _assert_no_daisyui(resp.text)

    def test_dashboard_has_new_design(self):
        client = _build_client(self._build_dashboard_db())
        resp = client.get("/")
        _assert_new_design(resp.text)


# ---------------------------------------------------------------------------
# Tests: Search page
# ---------------------------------------------------------------------------


class TestSearchPage:
    def test_search_page_renders(self):
        client = _build_client(MockDB(scalar=0, default=[]))
        resp = client.get("/search")
        assert resp.status_code == 200

    def test_search_has_input_with_debounce(self):
        client = _build_client(MockDB(scalar=0, default=[]))
        resp = client.get("/search")
        html = resp.text
        assert 'hx-trigger="keyup changed delay:500ms"' in html
        assert 'name="query"' in html

    def test_search_has_htmx_form(self):
        client = _build_client(MockDB(scalar=0, default=[]))
        resp = client.get("/search")
        html = resp.text
        assert 'hx-post="/api/search"' in html
        assert 'hx-target="#search-results"' in html

    def test_search_has_suggestion_chips(self):
        client = _build_client(MockDB(scalar=0, default=[]))
        resp = client.get("/search")
        html = resp.text
        assert "deployment steps" in html
        assert "pricing breakdown" in html

    def test_search_has_loading_indicator(self):
        client = _build_client(MockDB(scalar=0, default=[]))
        resp = client.get("/search")
        assert 'id="search-loading"' in resp.text
        assert "htmx-indicator" in resp.text

    def test_search_has_prefill_script(self):
        client = _build_client(MockDB(scalar=0, default=[]))
        resp = client.get("/search")
        assert "URLSearchParams" in resp.text
        assert "qs.get('q')" in resp.text

    def test_search_no_daisyui(self):
        client = _build_client(MockDB(scalar=0, default=[]))
        resp = client.get("/search")
        _assert_no_daisyui(resp.text)


# ---------------------------------------------------------------------------
# Tests: Queue page
# ---------------------------------------------------------------------------


class TestQueuePage:
    def _build_queue_db(self):
        return MockDB(
            execute_1=[_make_job(status="running", progress_pct=60)],
            execute_2=[_make_job(status="queued")],
            execute_3=[_make_job(status="completed")],
            execute_4=[],
            execute_5=[],
            default=[],
        )

    def test_queue_page_renders(self):
        client = _build_client(self._build_queue_db())
        resp = client.get("/queue")
        assert resp.status_code == 200

    def test_queue_has_title(self):
        client = _build_client(self._build_queue_db())
        resp = client.get("/queue")
        assert "Processing Queue" in resp.text

    def test_queue_has_polling(self):
        client = _build_client(self._build_queue_db())
        resp = client.get("/queue")
        html = resp.text
        assert 'hx-get="/queue"' in html
        assert 'hx-trigger="load delay:' in html

    def test_queue_htmx_returns_partial(self):
        client = _build_client(self._build_queue_db())
        resp = client.get("/queue", headers={"HX-Request": "true"})
        assert resp.status_code == 200
        # Partial should not contain full page layout
        assert "<html" not in resp.text
        assert "queue-summary" in resp.text

    def test_queue_no_daisyui(self):
        client = _build_client(self._build_queue_db())
        resp = client.get("/queue")
        _assert_no_daisyui(resp.text)


# ---------------------------------------------------------------------------
# Tests: Error page
# ---------------------------------------------------------------------------


class TestErrorPage:
    def test_error_renders_404(self):
        """Accessing a non-existent video should render error page."""
        fake_vid = uuid.uuid4()
        client = _build_client(MockDB(execute_1=None, default=None))
        resp = client.get(f"/videos/{fake_vid}")
        assert resp.status_code == 404
        html = resp.text
        assert "Error" in html
        assert "Video not found" in html
        assert "iconoir-warning-triangle" in html
        assert "Back to Dashboard" in html


# ---------------------------------------------------------------------------
# Tests: Legacy redirects
# ---------------------------------------------------------------------------


class TestLegacyRedirects:
    def test_submit_redirects_to_dashboard(self):
        client = _build_client(MockDB())
        resp = client.get("/submit", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"

    def test_channels_redirects_to_library(self):
        client = _build_client(MockDB(scalar=0, default=[]))
        resp = client.get("/channels", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/library?tab=channels"


# ---------------------------------------------------------------------------
# Tests: Videos page
# ---------------------------------------------------------------------------


class TestVideosPage:
    def _build_videos_db(self):
        videos = [_make_video(), _make_video(title="Second Video")]
        return MockDB(scalar=2, execute_1=videos, default=[])

    def test_videos_page_renders(self):
        client = _build_client(self._build_videos_db())
        resp = client.get("/videos")
        assert resp.status_code == 200

    def test_videos_has_title(self):
        client = _build_client(self._build_videos_db())
        resp = client.get("/videos")
        assert "Videos" in resp.text

    def test_videos_has_htmx_container(self):
        client = _build_client(self._build_videos_db())
        resp = client.get("/videos")
        html = resp.text
        assert 'id="video-list-container"' in html
        assert 'hx-push-url="true"' in html

    def test_videos_no_daisyui(self):
        client = _build_client(self._build_videos_db())
        resp = client.get("/videos")
        _assert_no_daisyui(resp.text)


# ---------------------------------------------------------------------------
# Tests: Chat page
# ---------------------------------------------------------------------------


def _make_chat_session(**overrides):
    from datetime import timezone
    defaults = dict(
        id=uuid.uuid4(),
        title="Test Chat Session",
        platform="web",
        created_at=_NOW.replace(tzinfo=timezone.utc) if _NOW.tzinfo is None else _NOW,
        updated_at=_NOW.replace(tzinfo=timezone.utc) if _NOW.tzinfo is None else _NOW,
        messages=[],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestChatPage:
    def _build_chat_db(self, sessions=None):
        """Chat page does: execute_1=sessions list, execute_2=session detail, scalar=video count."""
        if sessions is None:
            sessions = [_make_chat_session()]
        return MockDB(
            execute_1=sessions,
            execute_2=sessions[0] if sessions else None,
            scalar=5,
            default=[],
        )

    def test_chat_page_renders_200(self):
        client = _build_client(self._build_chat_db())
        resp = client.get("/chat")
        assert resp.status_code == 200

    def test_chat_page_has_layout(self):
        client = _build_client(self._build_chat_db())
        resp = client.get("/chat")
        html = resp.text
        assert "chat-sidebar" in html
        assert "chat-messages" in html
        assert "chat-input" in html
        assert "chat-send-btn" in html

    def test_chat_page_shows_video_count(self):
        client = _build_client(self._build_chat_db())
        resp = client.get("/chat")
        assert "5 videos active" in resp.text

    def test_chat_page_has_new_chat_button(self):
        client = _build_client(self._build_chat_db())
        resp = client.get("/chat")
        assert "New Chat" in resp.text

    def test_chat_page_empty_state(self):
        db = MockDB(execute_1=[], scalar=3, default=[])
        client = _build_client(db)
        resp = client.get("/chat")
        assert resp.status_code == 200
        assert "Chat with your library" in resp.text

    def test_chat_page_no_daisyui(self):
        client = _build_client(self._build_chat_db())
        resp = client.get("/chat")
        _assert_no_daisyui(resp.text)

    def test_chat_session_page_404(self):
        db = MockDB(execute_1=None, scalar=0, default=[])
        client = _build_client(db)
        resp = client.get(f"/chat/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_chat_nav_link_in_base(self):
        client = _build_client(self._build_chat_db())
        resp = client.get("/chat")
        html = resp.text
        assert 'href="/chat"' in html
        assert "is-active" in html

    def test_chat_page_has_marked_js(self):
        client = _build_client(self._build_chat_db())
        resp = client.get("/chat")
        assert "marked" in resp.text

    def test_chat_page_has_mobile_sidebar_toggle(self):
        client = _build_client(self._build_chat_db())
        resp = client.get("/chat")
        html = resp.text
        assert "chat-mobile-toggle" in html
        assert "sidebar-overlay" in html
        assert "toggleSidebar" in html

    def test_chat_page_has_send_on_enter(self):
        client = _build_client(self._build_chat_db())
        resp = client.get("/chat")
        assert "handleInputKey" in resp.text

    def test_chat_page_sidebar_shows_session(self):
        session = _make_chat_session(title="My Test Session")
        client = _build_client(self._build_chat_db(sessions=[session]))
        resp = client.get("/chat")
        assert "My Test Session" in resp.text

    def test_chat_page_sidebar_date_grouping(self):
        session = _make_chat_session(title="Grouped Session")
        client = _build_client(self._build_chat_db(sessions=[session]))
        resp = client.get("/chat")
        html = resp.text
        assert "chat-sidebar-group-label" in html
        # _NOW is 2025-06-01 which is in the "Older" group relative to real now
        assert "Older" in html

    def test_chat_session_page_with_messages(self):
        sid = uuid.uuid4()
        messages = [
            SimpleNamespace(
                id=uuid.uuid4(), role="user", content="Hello",
                sources=None, created_at=_NOW,
            ),
            SimpleNamespace(
                id=uuid.uuid4(), role="assistant",
                content="Hi! Based on your transcripts...",
                sources=[{
                    "video_title": "Test Video",
                    "start_time": 120,
                    "end_time": 180,
                    "similarity": 0.92,
                    "chunk_text": "Some transcript chunk",
                }],
                created_at=_NOW,
            ),
        ]
        session = _make_chat_session(id=sid, title="Session With Msgs", messages=messages)
        # session page: execute_1=session detail, execute_2=sessions list, scalar=video count
        db = MockDB(execute_1=session, execute_2=[session], scalar=3, default=[])
        client = _build_client(db)
        resp = client.get(f"/chat/{sid}")
        assert resp.status_code == 200
        html = resp.text
        assert "Hello" in html
        assert "chat-msg-avatar" in html
        assert "chat-source-card" in html
        assert "Test Video" in html
        assert "92%" in html
        assert "chat-md-content" in html

    def test_chat_page_input_disabled_when_no_session(self):
        db = MockDB(execute_1=[], scalar=0, default=[])
        client = _build_client(db)
        resp = client.get("/chat")
        html = resp.text
        assert "disabled" in html

    def test_chat_page_main_class_override(self):
        """Chat page should override main_class to remove page-shell."""
        client = _build_client(self._build_chat_db())
        resp = client.get("/chat")
        html = resp.text
        # chat.html sets block main_class to empty, so main tag shouldn't have page-shell
        assert 'class="chat-page-shell"' in html

    def test_chat_page_new_design_markers(self):
        client = _build_client(self._build_chat_db())
        resp = client.get("/chat")
        _assert_new_design(resp.text)
        _assert_no_daisyui(resp.text)


# ---------------------------------------------------------------------------
# Tests: _group_sessions_by_date helper
# ---------------------------------------------------------------------------


class TestGroupSessionsByDate:
    def test_empty_sessions(self):
        from app.routers.pages import _group_sessions_by_date
        result = _group_sessions_by_date([])
        assert result == []

    def test_today_group(self):
        from app.routers.pages import _group_sessions_by_date
        now = datetime.now(timezone.utc)
        s = SimpleNamespace(updated_at=now)
        groups = _group_sessions_by_date([s])
        assert len(groups) == 1
        assert groups[0][0] == "Today"
        assert groups[0][1] == [s]

    def test_multiple_groups_ordered(self):
        from app.routers.pages import _group_sessions_by_date
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        today_s = SimpleNamespace(updated_at=now)
        old_s = SimpleNamespace(updated_at=now - timedelta(days=30))
        groups = _group_sessions_by_date([today_s, old_s])
        labels = [g[0] for g in groups]
        assert labels == ["Today", "Older"]

    def test_naive_datetime_handled(self):
        from app.routers.pages import _group_sessions_by_date
        # Sessions with naive datetime (no tzinfo) should not crash
        naive_dt = datetime(2020, 1, 1, 12, 0, 0)
        s = SimpleNamespace(updated_at=naive_dt)
        groups = _group_sessions_by_date([s])
        assert len(groups) == 1
        assert groups[0][0] == "Older"


# ---------------------------------------------------------------------------
# Tests: Chat UI XSS and edge cases
# ---------------------------------------------------------------------------


class TestChatXSSAndEdgeCases:
    """Verify XSS escaping, newline handling, and edge cases in chat templates."""

    def _build_session_with_messages(self, messages):
        sid = uuid.uuid4()
        session = _make_chat_session(id=sid, messages=messages)
        db = MockDB(execute_1=session, execute_2=[session], scalar=1, default=[])
        return _build_client(db), sid

    def _make_msg(self, role="user", content="hi", sources=None):
        return SimpleNamespace(
            id=uuid.uuid4(), role=role, content=content,
            sources=sources, created_at=_NOW,
        )

    def test_user_message_script_tag_escaped(self):
        msgs = [self._make_msg("user", "<script>alert('xss')</script>")]
        client, sid = self._build_session_with_messages(msgs)
        resp = client.get(f"/chat/{sid}")
        html = resp.text
        assert "<script>alert(" not in html.split("chat-msg-content")[1]
        assert "&lt;script&gt;" in html

    def test_user_message_html_injection_escaped(self):
        msgs = [self._make_msg("user", '<img src=x onerror="alert(1)">')]
        client, sid = self._build_session_with_messages(msgs)
        resp = client.get(f"/chat/{sid}")
        html = resp.text
        assert 'onerror="alert(1)"' not in html

    def test_assistant_message_escaped_before_marked(self):
        """Assistant content is escaped in template; marked.js processes it client-side."""
        msgs = [self._make_msg("assistant", '<div onclick="evil()">Click</div>')]
        client, sid = self._build_session_with_messages(msgs)
        resp = client.get(f"/chat/{sid}")
        html = resp.text
        assert 'onclick="evil()"' not in html

    def test_source_title_xss_escaped(self):
        sources = [{"video_title": "<b onmouseover=alert(1)>evil</b>",
                     "chunk_text": "safe text", "start_time": 0, "end_time": 5, "similarity": 0.9}]
        msgs = [self._make_msg("assistant", "Answer.", sources=sources)]
        client, sid = self._build_session_with_messages(msgs)
        resp = client.get(f"/chat/{sid}")
        html = resp.text
        # The raw <b> tag should be escaped — no unescaped HTML attribute injection
        assert '<b onmouseover=alert(1)>' not in html
        assert '&lt;b onmouseover=alert(1)&gt;' in html

    def test_source_chunk_text_xss_escaped(self):
        sources = [{"video_title": "Safe Title",
                     "chunk_text": "<script>steal()</script>", "start_time": 0, "end_time": 5, "similarity": 0.8}]
        msgs = [self._make_msg("assistant", "Answer.", sources=sources)]
        client, sid = self._build_session_with_messages(msgs)
        resp = client.get(f"/chat/{sid}")
        html = resp.text
        assert "<script>steal()</script>" not in html

    def test_user_message_newlines_use_pre_wrap(self):
        """User messages should use white-space:pre-wrap for newline rendering."""
        msgs = [self._make_msg("user", "line1\nline2\nline3")]
        client, sid = self._build_session_with_messages(msgs)
        resp = client.get(f"/chat/{sid}")
        html = resp.text
        assert "pre-wrap" in html

    def test_empty_sources_no_source_section(self):
        msgs = [self._make_msg("assistant", "No sources here.", sources=[])]
        client, sid = self._build_session_with_messages(msgs)
        resp = client.get(f"/chat/{sid}")
        html = resp.text
        # "chat-source-card" appears in JS code; check that no actual source cards rendered
        # by verifying the sources toggle button is absent in the message area
        msg_area = html.split("chat-messages-inner")[1].split("chat-input-bar")[0]
        assert "chat-sources-toggle" not in msg_area

    def test_session_title_xss_escaped_in_sidebar(self):
        session = _make_chat_session(title="<script>alert('sidebar')</script>")
        db = MockDB(execute_1=[session], execute_2=session, scalar=0, default=[])
        client = _build_client(db)
        resp = client.get("/chat")
        html = resp.text
        assert "<script>alert(" not in html.split("chat-sidebar")[1]
