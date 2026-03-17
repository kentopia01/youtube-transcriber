"""Tests for channel video filtering: discover_channel_videos filters, API filter params, and latest-N processing."""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_db
from app.main import create_app
from app.services.youtube import discover_channel_videos


# ---------------------------------------------------------------------------
# discover_channel_videos unit tests (mock yt-dlp)
# ---------------------------------------------------------------------------

FAKE_CHANNEL_INFO = {
    "channel": "TestChannel",
    "channel_id": "UC12345",
    "description": "A test channel",
    "title": "TestChannel",
    "id": "UC12345",
    "thumbnails": [{"url": "https://example.com/thumb.jpg"}],
    "entries": [
        {"id": "vid1", "title": "Video 1", "duration": 120, "url": "https://youtube.com/watch?v=vid1", "thumbnails": [{"url": "https://example.com/v1.jpg"}]},
        {"id": "vid2", "title": "Video 2", "duration": 300, "url": "https://youtube.com/watch?v=vid2", "thumbnails": [{"url": "https://example.com/v2.jpg"}]},
        {"id": "vid3", "title": "Video 3", "duration": 600, "url": "https://youtube.com/watch?v=vid3", "thumbnails": []},
    ],
}


def _mock_extract(channel_url, download=False):
    return FAKE_CHANNEL_INFO


class TestDiscoverChannelVideosFilters:
    @patch("app.services.youtube.yt_dlp.YoutubeDL")
    def test_no_filters(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = _mock_extract
        mock_ydl.__enter__ = lambda s: s
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl_cls.return_value = mock_ydl

        result = discover_channel_videos("https://youtube.com/@test")
        assert len(result["videos"]) == 3
        assert result["channel_name"] == "TestChannel"
        # No special yt-dlp opts should be set
        opts = mock_ydl_cls.call_args[0][0]
        assert "playlistend" not in opts
        assert "daterange" not in opts
        assert "match_filter" not in opts
        mock_ydl.extract_info.assert_called_once_with("https://youtube.com/@test/videos", download=False)

    @patch("app.services.youtube.yt_dlp.YoutubeDL")
    def test_limit_sets_playlistend(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = _mock_extract
        mock_ydl.__enter__ = lambda s: s
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl_cls.return_value = mock_ydl

        discover_channel_videos("https://youtube.com/@test", limit=5)
        opts = mock_ydl_cls.call_args[0][0]
        assert opts["playlistend"] == 5

    @patch("app.services.youtube.yt_dlp.YoutubeDL")
    def test_date_filters_set_daterange(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = _mock_extract
        mock_ydl.__enter__ = lambda s: s
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl_cls.return_value = mock_ydl

        discover_channel_videos(
            "https://youtube.com/@test",
            after_date="2024-01-01",
            before_date="2024-12-31",
        )
        opts = mock_ydl_cls.call_args[0][0]
        assert "daterange" in opts

    @patch("app.services.youtube.yt_dlp.YoutubeDL")
    def test_duration_filters_set_match_filter(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = _mock_extract
        mock_ydl.__enter__ = lambda s: s
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl_cls.return_value = mock_ydl

        discover_channel_videos(
            "https://youtube.com/@test",
            min_duration=60,
            max_duration=600,
        )
        opts = mock_ydl_cls.call_args[0][0]
        assert "match_filter" in opts
        assert callable(opts["match_filter"])

    @patch("app.services.youtube.yt_dlp.YoutubeDL")
    def test_after_date_only(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = _mock_extract
        mock_ydl.__enter__ = lambda s: s
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl_cls.return_value = mock_ydl

        discover_channel_videos("https://youtube.com/@test", after_date="2024-06-01")
        opts = mock_ydl_cls.call_args[0][0]
        assert "daterange" in opts

    @patch("app.services.youtube.yt_dlp.YoutubeDL")
    def test_min_duration_only(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = _mock_extract
        mock_ydl.__enter__ = lambda s: s
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl_cls.return_value = mock_ydl

        discover_channel_videos("https://youtube.com/@test", min_duration=120)
        opts = mock_ydl_cls.call_args[0][0]
        assert "match_filter" in opts


# ---------------------------------------------------------------------------
# API tests - DB stub (reuse pattern from test_api_endpoints.py)
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value if isinstance(self._value, list) else []

    def first(self):
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value


class StubDB:
    def __init__(self, execute_results=None):
        self._results = list(execute_results or [])
        self.added = []
        self.committed = False
        self._exec_idx = 0

    async def execute(self, *args, **kwargs):
        if self._exec_idx < len(self._results):
            val = self._results[self._exec_idx]
            self._exec_idx += 1
            return _FakeResult(val)
        return _FakeResult(None)

    async def scalar(self, *args, **kwargs):
        return 0

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if hasattr(obj, "id") and obj.id is None:
                obj.id = uuid.uuid4()

    async def commit(self):
        self.committed = True


def _build_client(db=None):
    app = create_app()

    async def _override():
        yield db or StubDB()

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


# ---------------------------------------------------------------------------
# API tests for POST /api/channels with filter params
# ---------------------------------------------------------------------------


MOCK_DISCOVER_RESULT = {
    "channel_name": "TestChannel",
    "channel_id": "UC12345",
    "description": "A test channel",
    "thumbnail": "https://example.com/thumb.jpg",
    "videos": [
        {"video_id": "vid1", "title": "Video 1", "duration": 120, "url": "https://youtube.com/watch?v=vid1", "thumbnail": None},
        {"video_id": "vid2", "title": "Video 2", "duration": 300, "url": "https://youtube.com/watch?v=vid2", "thumbnail": None},
    ],
}


class TestChannelSubmitFilters:
    @patch("app.routers.channels.discover_channel_videos", return_value=MOCK_DISCOVER_RESULT)
    def test_submit_with_limit(self, mock_discover):
        db = StubDB(execute_results=[None])  # no existing channel
        client = _build_client(db)
        resp = client.post(
            "/api/channels",
            json={"url": "https://www.youtube.com/@testchannel", "limit": 10},
        )
        assert resp.status_code == 200
        mock_discover.assert_called_once()
        call_kwargs = mock_discover.call_args
        assert call_kwargs.kwargs["limit"] == 10

    @patch("app.routers.channels.discover_channel_videos", return_value=MOCK_DISCOVER_RESULT)
    def test_submit_with_date_filters(self, mock_discover):
        db = StubDB(execute_results=[None])
        client = _build_client(db)
        resp = client.post(
            "/api/channels",
            json={
                "url": "https://www.youtube.com/@testchannel",
                "after_date": "2024-01-01",
                "before_date": "2024-12-31",
            },
        )
        assert resp.status_code == 200
        call_kwargs = mock_discover.call_args
        assert call_kwargs.kwargs["after_date"] == "2024-01-01"
        assert call_kwargs.kwargs["before_date"] == "2024-12-31"

    @patch("app.routers.channels.discover_channel_videos", return_value=MOCK_DISCOVER_RESULT)
    def test_submit_with_duration_filters(self, mock_discover):
        db = StubDB(execute_results=[None])
        client = _build_client(db)
        resp = client.post(
            "/api/channels",
            json={
                "url": "https://www.youtube.com/@testchannel",
                "min_duration": 60,
                "max_duration": 3600,
            },
        )
        assert resp.status_code == 200
        call_kwargs = mock_discover.call_args
        assert call_kwargs.kwargs["min_duration"] == 60
        assert call_kwargs.kwargs["max_duration"] == 3600

    @patch("app.routers.channels.discover_channel_videos", return_value=MOCK_DISCOVER_RESULT)
    def test_submit_with_all_filters(self, mock_discover):
        db = StubDB(execute_results=[None])
        client = _build_client(db)
        resp = client.post(
            "/api/channels",
            json={
                "url": "https://www.youtube.com/@testchannel",
                "limit": 5,
                "after_date": "2024-01-01",
                "before_date": "2024-06-30",
                "min_duration": 120,
                "max_duration": 1800,
            },
        )
        assert resp.status_code == 200
        call_kwargs = mock_discover.call_args
        assert call_kwargs.kwargs["limit"] == 5
        assert call_kwargs.kwargs["after_date"] == "2024-01-01"
        assert call_kwargs.kwargs["min_duration"] == 120

    @patch("app.routers.channels.discover_channel_videos", return_value=MOCK_DISCOVER_RESULT)
    def test_submit_no_filters_still_works(self, mock_discover):
        db = StubDB(execute_results=[None])
        client = _build_client(db)
        resp = client.post(
            "/api/channels",
            json={"url": "https://www.youtube.com/@testchannel"},
        )
        assert resp.status_code == 200
        call_kwargs = mock_discover.call_args
        assert call_kwargs.kwargs["limit"] is None
        assert call_kwargs.kwargs["after_date"] is None

    @patch("app.routers.channels.discover_channel_videos", return_value=MOCK_DISCOVER_RESULT)
    def test_submit_persists_discovered_videos(self, mock_discover):
        db = StubDB(execute_results=[None, None, None])
        client = _build_client(db)

        resp = client.post(
            "/api/channels",
            json={"url": "https://www.youtube.com/@testchannel"},
        )

        assert resp.status_code == 200

        channel = next(obj for obj in db.added if hasattr(obj, "youtube_channel_id"))
        videos = [obj for obj in db.added if hasattr(obj, "youtube_video_id")]

        assert channel.youtube_channel_id == "UC12345"
        assert len(videos) == 2
        assert {video.youtube_video_id for video in videos} == {"vid1", "vid2"}
        assert all(video.channel_id == channel.id for video in videos)
        assert all(video.status == "discovered" for video in videos)
        assert videos[0].title == "Video 1"


# ---------------------------------------------------------------------------
# API tests for POST /api/channels/{id}/process with latest param
# ---------------------------------------------------------------------------


class TestProcessLatest:
    def test_process_no_videos_no_latest_returns_400(self):
        fake_channel = SimpleNamespace(id=uuid.uuid4(), name="TestChannel")
        db = StubDB(execute_results=[fake_channel])
        client = _build_client(db)
        resp = client.post(
            f"/api/channels/{fake_channel.id}/process",
            json={"video_ids": []},
        )
        assert resp.status_code == 400
        assert "No videos selected" in resp.json()["detail"]

    def test_process_with_explicit_video_ids(self):
        fake_channel = SimpleNamespace(id=uuid.uuid4(), name="TestChannel")
        db = StubDB(execute_results=[
            fake_channel,   # channel lookup
            None,           # video lookup (not found)
        ])
        client = _build_client(db)
        with patch("app.routers.channels.run_pipeline", return_value="celery-task-id"):
            resp = client.post(
                f"/api/channels/{fake_channel.id}/process",
                json={"video_ids": ["vid1"]},
            )
        assert resp.status_code == 200
        assert resp.json()["total_videos"] == 1

    def test_process_with_latest_param(self):
        """When latest is set and video_ids is empty, auto-select from DB."""
        fake_channel = SimpleNamespace(id=uuid.uuid4(), name="TestChannel")
        # Results: channel lookup, then latest query returns video IDs, then video lookup per video
        db = StubDB(execute_results=[
            fake_channel,           # channel lookup
            [("vid1",), ("vid2",)], # latest query results
            None,                   # video vid1 lookup
            None,                   # video vid2 lookup
        ])
        client = _build_client(db)
        with patch("app.routers.channels.run_pipeline", return_value="celery-task-id"):
            resp = client.post(
                f"/api/channels/{fake_channel.id}/process",
                json={"latest": 2},
            )
        assert resp.status_code == 200
        assert resp.json()["total_videos"] == 2

    def test_process_moves_discovered_video_to_pending(self):
        fake_channel = SimpleNamespace(id=uuid.uuid4(), name="TestChannel")
        existing_video = SimpleNamespace(
            id=uuid.uuid4(),
            youtube_video_id="vid1",
            channel_id=fake_channel.id,
            status="discovered",
            error_message="old error",
        )
        db = StubDB(execute_results=[
            fake_channel,
            existing_video,
        ])
        client = _build_client(db)

        with patch("app.routers.channels.run_pipeline", return_value="celery-task-id"):
            resp = client.post(
                f"/api/channels/{fake_channel.id}/process",
                json={"video_ids": ["vid1"]},
            )

        assert resp.status_code == 200
        assert existing_video.status == "pending"
        assert existing_video.error_message is None


# ---------------------------------------------------------------------------
# Validation edge-case tests
# ---------------------------------------------------------------------------


class TestChannelSubmitValidation:
    def test_limit_zero_rejected(self):
        client = _build_client()
        resp = client.post(
            "/api/channels",
            json={"url": "https://www.youtube.com/@testchannel", "limit": 0},
        )
        assert resp.status_code == 422

    def test_limit_negative_rejected(self):
        client = _build_client()
        resp = client.post(
            "/api/channels",
            json={"url": "https://www.youtube.com/@testchannel", "limit": -5},
        )
        assert resp.status_code == 422

    def test_invalid_date_format_rejected(self):
        client = _build_client()
        resp = client.post(
            "/api/channels",
            json={"url": "https://www.youtube.com/@testchannel", "after_date": "not-a-date"},
        )
        assert resp.status_code == 422

    def test_negative_duration_rejected(self):
        client = _build_client()
        resp = client.post(
            "/api/channels",
            json={"url": "https://www.youtube.com/@testchannel", "min_duration": -100},
        )
        assert resp.status_code == 422


class TestProcessLatestValidation:
    def test_latest_zero_rejected(self):
        fake_channel = SimpleNamespace(id=uuid.uuid4(), name="TestChannel")
        client = _build_client()
        resp = client.post(
            f"/api/channels/{fake_channel.id}/process",
            json={"latest": 0},
        )
        assert resp.status_code == 422

    def test_latest_negative_rejected(self):
        fake_channel = SimpleNamespace(id=uuid.uuid4(), name="TestChannel")
        client = _build_client()
        resp = client.post(
            f"/api/channels/{fake_channel.id}/process",
            json={"latest": -1},
        )
        assert resp.status_code == 422
