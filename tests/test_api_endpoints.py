"""Tests for API endpoints: video submission, channel submission, job actions, search."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.dependencies import get_db
from app.main import create_app
from app.routers import global_search as global_search_router
from app.routers import search as search_router


# ---------------------------------------------------------------------------
# DB mock
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
    """Minimal async DB stub for API route tests."""

    def __init__(self, execute_results=None, scalar_value=0):
        self._results = list(execute_results or [])
        self._scalar = scalar_value
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
        return self._scalar

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
# Video submission tests
# ---------------------------------------------------------------------------


class TestVideoSubmission:
    def test_rejects_channel_url(self):
        client = _build_client()
        resp = client.post("/api/videos", json={"url": "https://www.youtube.com/@openai"})
        assert resp.status_code == 400
        assert "channel URL" in resp.json()["detail"]

    def test_rejects_invalid_url(self):
        client = _build_client()
        resp = client.post("/api/videos", json={"url": "https://www.google.com"})
        assert resp.status_code == 400
        assert "video ID" in resp.json()["detail"]

    def test_rejects_empty_url(self):
        client = _build_client()
        resp = client.post("/api/videos", json={"url": ""})
        assert resp.status_code == 400

    @patch("app.routers.videos.get_video_info")
    @patch("app.routers.videos.run_pipeline", return_value="celery-task-id")
    def test_submit_creates_channel_and_links_video(self, mock_run_pipeline, mock_get_video_info):
        mock_get_video_info.return_value = {
            "video_id": "dQw4w9WgXcQ",
            "title": "Test Video",
            "description": "Desc",
            "duration": 42,
            "thumbnail": "https://example.com/thumb.jpg",
            "channel_id": "UC12345",
            "channel_name": "Test Channel",
            "channel_url": "https://www.youtube.com/@testchannel",
            "published_at": "20260317",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }

        db = StubDB(execute_results=[None, None])
        client = _build_client(db)

        resp = client.post(
            "/api/videos",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )

        assert resp.status_code == 200
        channel = next(obj for obj in db.added if hasattr(obj, "youtube_channel_id"))
        video = next(obj for obj in db.added if hasattr(obj, "youtube_video_id"))
        assert channel.youtube_channel_id == "UC12345"
        assert video.channel_id == channel.id
        assert video.title == "Test Video"


class TestTranscriptionEndpoint:
    def test_transcription_sanitizes_non_finite_floats(self):
        video_id = uuid.uuid4()
        transcription = SimpleNamespace(
            id=uuid.uuid4(),
            video_id=video_id,
            full_text="hello world",
            language="en",
            model_size="test",
            word_count=2,
            processing_time_seconds=float("nan"),
            segments=[
                SimpleNamespace(
                    segment_index=0,
                    start_time=0.0,
                    end_time=1.5,
                    text="hello",
                    confidence=float("nan"),
                    speaker="SPEAKER_00",
                ),
                SimpleNamespace(
                    segment_index=1,
                    start_time=float("nan"),
                    end_time=float("inf"),
                    text="world",
                    confidence=0.9,
                    speaker=None,
                ),
            ],
        )
        client = _build_client(StubDB(execute_results=[transcription, None]))

        resp = client.get(f"/api/transcriptions/{video_id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["processing_time_seconds"] is None
        assert body["segments"][0]["confidence"] is None
        assert body["segments"][1]["start"] is None
        assert body["segments"][1]["end"] is None
        assert body["segments"][1]["confidence"] == 0.9


# ---------------------------------------------------------------------------
# Channel submission tests
# ---------------------------------------------------------------------------


class TestChannelSubmission:
    def test_rejects_video_url(self):
        client = _build_client()
        resp = client.post(
            "/api/channels",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        assert resp.status_code == 400
        assert "channel URL" in resp.json()["detail"]

    def test_rejects_empty_url(self):
        client = _build_client()
        resp = client.post("/api/channels", json={"url": ""})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Search endpoint tests
# ---------------------------------------------------------------------------


class TestSearchEndpoint:
    def test_empty_form_query_returns_empty(self):
        client = _build_client()
        resp = client.post("/api/search", data={"query": ""})
        assert resp.status_code == 200

    def test_htmx_form_search(self, monkeypatch):
        async def fake_search(db, query_embedding, limit=10, channel_id=None, **kwargs):
            return [
                {
                    "video_id": str(uuid.uuid4()),
                    "video_title": "Test Result",
                    "chunk_text": "Some transcript chunk",
                    "start_time": 10.0,
                    "end_time": 25.0,
                    "similarity": 0.91,
                }
            ]

        monkeypatch.setattr(
            "app.services.search.encode_query",
            lambda query, model_cache_dir=None: [0.1] * 384,
        )
        monkeypatch.setattr(search_router, "semantic_search", fake_search)

        client = _build_client()
        resp = client.post(
            "/api/search",
            data={"query": "machine learning"},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "Test Result" in resp.text
        assert "91.0% match" in resp.text

    def test_json_search(self, monkeypatch):
        async def fake_search(db, query_embedding, limit=10, channel_id=None, **kwargs):
            return [
                {
                    "video_id": str(uuid.uuid4()),
                    "video_title": "JSON Result",
                    "chunk_text": "content",
                    "similarity": 0.85,
                }
            ]

        monkeypatch.setattr(
            "app.services.search.encode_query",
            lambda query, model_cache_dir=None: [0.2] * 384,
        )
        monkeypatch.setattr(search_router, "semantic_search", fake_search)

        client = _build_client()
        resp = client.post("/api/search", json={"query": "test topic"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "test topic"
        assert len(body["results"]) == 1
        assert body["results"][0]["video_title"] == "JSON Result"

    def test_htmx_empty_results(self, monkeypatch):
        async def fake_search(db, query_embedding, limit=10, channel_id=None, **kwargs):
            return []

        monkeypatch.setattr(
            "app.services.search.encode_query",
            lambda query, model_cache_dir=None: [0.0] * 384,
        )
        monkeypatch.setattr(search_router, "semantic_search", fake_search)

        client = _build_client()
        resp = client.post(
            "/api/search",
            data={"query": "nonexistent content"},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "No results" in resp.text

    def test_search_no_daisyui_in_results(self, monkeypatch):
        async def fake_search(db, query_embedding, limit=10, channel_id=None, **kwargs):
            return [
                {
                    "video_id": str(uuid.uuid4()),
                    "video_title": "A Result",
                    "chunk_text": "text",
                    "start_time": 0.0,
                    "end_time": 5.0,
                    "similarity": 0.9,
                }
            ]

        monkeypatch.setattr(
            "app.services.search.encode_query",
            lambda query, model_cache_dir=None: [0.1] * 384,
        )
        monkeypatch.setattr(search_router, "semantic_search", fake_search)

        client = _build_client()
        resp = client.post(
            "/api/search",
            data={"query": "test"},
            headers={"HX-Request": "true"},
        )
        assert "badge-" not in resp.text
        assert "card-body" not in resp.text


# ---------------------------------------------------------------------------
# Global search endpoint tests
# ---------------------------------------------------------------------------


class TestGlobalSearchEndpoint:
    def test_empty_form_query_returns_empty(self):
        client = _build_client()
        resp = client.post("/api/global-search", data={"query": ""})
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    def test_json_global_search(self, monkeypatch):
        async def fake_global_search(db, query, query_embedding, options):
            return {
                "query": query,
                "results": [
                    {
                        "rank": 1,
                        "video_id": str(uuid.uuid4()),
                        "video_title": "Global Result",
                        "source_type": "transcript",
                        "evidence_text": "Useful transcript evidence",
                        "fused_score": 0.03,
                        "score_components": {"vector": 0.02, "keyword": 0.01},
                    }
                ],
                "candidate_count": 1,
                "lane_counts": {"vector": 1, "keyword": 1, "summary": 0},
                "options": {"source_type": options.source_type},
            }

        monkeypatch.setattr(
            "app.services.search.encode_query",
            lambda query, model_cache_dir=None: [0.1] * 768,
        )
        monkeypatch.setattr(global_search_router, "run_global_search", fake_global_search)

        client = _build_client()
        resp = client.post(
            "/api/global-search",
            json={
                "query": "deployment",
                "source_type": "transcript",
                "candidate_limit": 40,
                "summary_limit": 10,
                "per_video_limit": 2,
                "rrf_k": 30,
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "deployment"
        assert body["results"][0]["video_title"] == "Global Result"
        assert body["options"]["source_type"] == "transcript"

    def test_json_global_search_passes_benchmark_tuning_knobs(self, monkeypatch):
        captured = {}

        async def fake_global_search(db, query, query_embedding, options):
            captured["options"] = options
            return {
                "query": query,
                "results": [],
                "candidate_count": 0,
                "lane_counts": {"vector": 0, "keyword": 0, "summary": 0},
                "options": {},
            }

        monkeypatch.setattr(
            "app.services.search.encode_query",
            lambda query, model_cache_dir=None: [0.1] * 768,
        )
        monkeypatch.setattr(global_search_router, "run_global_search", fake_global_search)

        client = _build_client()
        resp = client.post(
            "/api/global-search",
            json={
                "query": "deployment",
                "candidate_limit": 40,
                "summary_limit": 10,
                "per_video_limit": 2,
                "rrf_k": 30,
            },
        )

        assert resp.status_code == 200
        options = captured["options"]
        assert options.candidate_limit == 40
        assert options.summary_limit == 10
        assert options.per_video_limit == 2
        assert options.rrf_k == 30

    def test_htmx_global_search(self, monkeypatch):
        async def fake_global_search(db, query, query_embedding, options):
            return {
                "query": query,
                "results": [
                    {
                        "rank": 1,
                        "video_id": str(uuid.uuid4()),
                        "video_title": "HTMX Global Result",
                        "channel_name": "A Channel",
                        "source_type": "summary",
                        "evidence_text": "Summary evidence",
                        "start_time": None,
                        "end_time": None,
                        "youtube_url": None,
                        "fused_score": 0.0328,
                        "score_components": {"summary": 0.0328},
                    }
                ],
                "candidate_count": 1,
                "lane_counts": {"vector": 0, "keyword": 0, "summary": 1},
                "options": {},
            }

        monkeypatch.setattr(
            "app.services.search.encode_query",
            lambda query, model_cache_dir=None: [0.1] * 768,
        )
        monkeypatch.setattr(global_search_router, "run_global_search", fake_global_search)

        client = _build_client()
        resp = client.post(
            "/api/global-search",
            data={"query": "themes", "source_type": "summary"},
            headers={"HX-Request": "true"},
        )

        assert resp.status_code == 200
        assert "HTMX Global Result" in resp.text
        assert "Summary evidence" in resp.text
        assert "summary 1" in resp.text


# ---------------------------------------------------------------------------
# Job API tests
# ---------------------------------------------------------------------------


class TestJobCancel:
    def test_cancel_nonexistent_job_returns_404(self):
        client = _build_client(StubDB(execute_results=[None]))
        fake_id = uuid.uuid4()
        resp = client.post(f"/api/jobs/{fake_id}/cancel")
        assert resp.status_code == 404

    def test_cancel_completed_job_returns_400(self):
        job = SimpleNamespace(
            id=uuid.uuid4(), status="completed", job_type="pipeline",
            video_id=None, channel_id=None, batch_id=None,
            celery_task_id=None, progress_pct=100.0,
            progress_message="Done", error_message=None,
            started_at=None, completed_at=None, created_at=None,
        )
        client = _build_client(StubDB(execute_results=[job]))
        resp = client.post(f"/api/jobs/{job.id}/cancel")
        assert resp.status_code == 400

    def test_cancel_pending_job_succeeds(self):
        job = SimpleNamespace(
            id=uuid.uuid4(), status="pending", job_type="pipeline",
            video_id=None, channel_id=None, batch_id=None,
            celery_task_id=None, progress_pct=0.0,
            progress_message=None, error_message=None,
            started_at=None, completed_at=None, created_at=None,
        )
        db = StubDB(execute_results=[job])
        client = _build_client(db)
        resp = client.post(f"/api/jobs/{job.id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
        assert job.status == "cancelled"


class TestJobRetry:
    def test_retry_nonexistent_returns_404(self):
        client = _build_client(StubDB(execute_results=[None]))
        resp = client.post(f"/api/jobs/{uuid.uuid4()}/retry")
        assert resp.status_code == 404

    def test_retry_completed_job_returns_400(self):
        job = SimpleNamespace(
            id=uuid.uuid4(), status="completed", job_type="pipeline",
            video_id=uuid.uuid4(), channel_id=None,
        )
        client = _build_client(StubDB(execute_results=[job]))
        resp = client.post(f"/api/jobs/{job.id}/retry")
        assert resp.status_code == 400
        assert "failed jobs" in resp.json()["detail"]
