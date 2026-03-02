import uuid

from fastapi.testclient import TestClient

from app.dependencies import get_db
from app.main import create_app
from app.routers import search as search_router


class DummyDB:
    async def execute(self, *args, **kwargs):
        raise AssertionError("Unexpected DB execute in this smoke test")

    async def scalar(self, *args, **kwargs):
        return 0

    async def commit(self):
        return None

    async def flush(self):
        return None


async def _override_get_db():
    yield DummyDB()


def _build_client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def test_search_page_renders():
    client = _build_client()
    response = client.get("/search")
    assert response.status_code == 200
    assert "Search across all transcribed video content" in response.text
    assert "top-nav" in response.text
    assert "Chat with Library" in response.text


def test_legacy_routes_redirect_to_new_locations():
    client = _build_client()

    submit_response = client.get("/submit", follow_redirects=False)
    assert submit_response.status_code == 302
    assert submit_response.headers["location"] == "/"

    channels_response = client.get("/channels", follow_redirects=False)
    assert channels_response.status_code == 302
    assert channels_response.headers["location"] == "/library?tab=channels"


def test_submit_video_rejects_channel_url():
    client = _build_client()
    response = client.post("/api/videos", json={"url": "https://www.youtube.com/@openai"})
    assert response.status_code == 400
    assert "channel URL" in response.json()["detail"]


def test_submit_channel_rejects_non_channel_url():
    client = _build_client()
    response = client.post(
        "/api/channels",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    )
    assert response.status_code == 400
    assert "channel URL" in response.json()["detail"]


def test_search_api_accepts_form_for_htmx(monkeypatch):
    async def fake_semantic_search(db, query_embedding, limit=10, channel_id=None):
        return [
            {
                "video_id": str(uuid.uuid4()),
                "video_title": "Roadmap Update",
                "chunk_text": "AI roadmap and release cadence.",
                "start_time": 12.0,
                "end_time": 30.0,
                "similarity": 0.93,
            }
        ]

    monkeypatch.setattr("app.services.search.encode_query", lambda query, model_cache_dir=None: [0.1, 0.2])
    monkeypatch.setattr(search_router, "semantic_search", fake_semantic_search)

    client = _build_client()
    response = client.post(
        "/api/search",
        data={"query": "roadmap"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert 'Found 1 results for "roadmap"' in response.text
    assert "Roadmap Update" in response.text


def test_search_api_accepts_json_payload(monkeypatch):
    async def fake_semantic_search(db, query_embedding, limit=10, channel_id=None):
        return [{"video_id": str(uuid.uuid4()), "video_title": "Result", "chunk_text": "x", "similarity": 0.8}]

    monkeypatch.setattr("app.services.search.encode_query", lambda query, model_cache_dir=None: [0.3, 0.4])
    monkeypatch.setattr(search_router, "semantic_search", fake_semantic_search)

    client = _build_client()
    response = client.post("/api/search", json={"query": "pricing strategy"})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "pricing strategy"
    assert len(body["results"]) == 1
