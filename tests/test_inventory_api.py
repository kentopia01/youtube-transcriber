from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.dependencies import get_db
from app.main import create_app


NOW = datetime(2026, 7, 22, tzinfo=UTC)


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _DB:
    def __init__(self, *, totals, rows):
        self.totals = list(totals)
        self.rows = list(rows)

    async def scalar(self, statement):
        return self.totals.pop(0)

    async def execute(self, statement):
        return _Result(self.rows.pop(0))


def _client(db):
    app = create_app()

    async def override():
        yield db

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def test_jobs_inventory_is_paginated_and_includes_video_context():
    video_id = uuid.uuid4()
    video = SimpleNamespace(id=video_id, title="A useful transcript", youtube_video_id="abcdefghijk")
    job = SimpleNamespace(
        id=uuid.uuid4(),
        video_id=video_id,
        channel_id=uuid.uuid4(),
        job_type="pipeline",
        status="completed",
        current_stage="completed",
        progress_pct=100.0,
        attempt_number=1,
        attempt_creation_reason="video_submit",
        error_message=None,
        hidden_from_queue=False,
        created_at=NOW,
        completed_at=NOW,
    )
    response = _client(_DB(totals=[1], rows=[[(job, video)]])).get(
        "/api/jobs?status=completed&limit=25&offset=0"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 25
    assert body["items"][0]["video_title"] == "A useful transcript"


def test_videos_inventory_exposes_transcript_and_reader_state():
    video = SimpleNamespace(
        id=uuid.uuid4(),
        youtube_video_id="abcdefghijk",
        channel_id=uuid.uuid4(),
        title="Read me",
        status="completed",
        duration_seconds=1200.0,
        published_at=NOW,
        thumbnail_url=None,
        dismissed_at=None,
        created_at=NOW,
    )
    channel = SimpleNamespace(name="Channel")
    state = SimpleNamespace(status="reading", progress_pct=42.5)
    response = _client(_DB(totals=[1], rows=[[(video, channel, state, uuid.uuid4())]])).get(
        "/api/videos?reader_status=reading"
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["has_transcript"] is True
    assert item["reader_status"] == "reading"
    assert item["reader_progress_pct"] == 42.5


def test_reader_state_inventory_is_local_owner_only_and_paginated():
    video = SimpleNamespace(
        id=uuid.uuid4(), title="Resume me", youtube_video_id="abcdefghijk"
    )
    state = SimpleNamespace(
        id=uuid.uuid4(),
        status="later",
        progress_pct=12.0,
        last_block_anchor="block-2",
        last_timestamp_seconds=80.0,
        last_read_at=NOW,
        updated_at=NOW,
    )
    channel = SimpleNamespace(name="Channel")
    response = _client(_DB(totals=[1], rows=[[(state, video, channel)]])).get(
        "/api/reader/states?status=later"
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["video_title"] == "Resume me"


def test_inventory_limits_are_bounded_and_reader_status_is_validated():
    client = _client(_DB(totals=[], rows=[]))
    assert client.get("/api/jobs?limit=201").status_code == 422
    assert client.get("/api/videos?reader_status=bogus").status_code == 422
    assert client.get("/api/reader/states?status=bogus").status_code == 422


def test_system_status_composes_existing_operations_truth():
    health = SimpleNamespace(state="idle", to_dict=lambda: {"state": "idle"})
    counts = SimpleNamespace(to_dict=lambda: {"total_videos": 617})
    runtime = SimpleNamespace(to_dict=lambda: {"transcription_engine": "faster-whisper"})
    summary = SimpleNamespace(
        generated_at=NOW,
        queue_health=health,
        counts=counts,
        runtime=runtime,
        warning_count=2,
    )
    with patch(
        "app.routers.system.build_operations_summary",
        AsyncMock(return_value=summary),
    ):
        response = _client(_DB(totals=[], rows=[])).get("/api/system/status")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["warning_count"] == 2
