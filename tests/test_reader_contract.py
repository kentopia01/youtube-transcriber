from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint

import app.models  # noqa: F401 - populate relationship registry and metadata
from app.database import Base
from app.dependencies import get_db
from app.main import create_app
from app.models.channel import Channel
from app.models.reader_state import ReaderState
from app.models.reader_annotation import ReaderAnnotation
from app.models.summary import Summary
from app.models.transcription import Transcription
from app.models.transcription_segment import TranscriptionSegment
from app.models.video import Video
from app.services.reader import (
    apply_reader_state_update,
    build_reader_blocks,
    resolve_resume_block,
)


def _segment(index, start, end, text, speaker=None):
    return SimpleNamespace(
        segment_index=index,
        start_time=start,
        end_time=end,
        text=text,
        speaker=speaker,
    )


def test_reader_blocks_are_deterministic_ordered_and_timestamp_preserving():
    segments = [
        _segment(2, 16, 22, "A second speaker answers.", "SPEAKER_01"),
        _segment(0, 0, 7, "The opening claim is clear.", "SPEAKER_00"),
        _segment(1, 7, 14, "It continues in the same paragraph.", "SPEAKER_00"),
    ]

    first = build_reader_blocks(segments)
    second = build_reader_blocks(reversed(segments))

    assert first == second
    assert len(first) == 2
    assert first[0].start_time == 0
    assert first[0].end_time == 14
    assert first[0].speaker == "SPEAKER_00"
    assert first[0].segment_start_index == 0
    assert first[0].segment_end_index == 1
    assert first[1].start_time == 16
    assert first[1].anchor.startswith("t-000016-")


def test_reader_blocks_fall_back_to_full_text_without_backfill():
    blocks = build_reader_blocks(
        [],
        full_text="First sentence. " * 100,
        duration_seconds=300,
    )

    assert len(blocks) > 1
    assert blocks[0].start_time == 0
    assert blocks[-1].end_time == pytest.approx(300)
    assert all(block.text for block in blocks)


def test_resume_uses_anchor_then_timestamp_after_regeneration():
    blocks = build_reader_blocks(
        [
            _segment(0, 0, 10, "First block."),
            _segment(1, 20, 30, "Second block."),
        ],
        max_seconds=5,
    )

    assert resolve_resume_block(blocks, anchor=blocks[1].anchor, timestamp_seconds=0) == blocks[1]
    assert resolve_resume_block(blocks, anchor="old-anchor", timestamp_seconds=24) == blocks[1]


def test_reader_state_transitions_and_progress_are_bounded():
    state = ReaderState(status="unread", progress_pct=0)
    now = datetime(2026, 7, 21, tzinfo=UTC)
    apply_reader_state_update(
        state,
        status="reading",
        progress_pct=42,
        last_block_anchor="t-000120-example",
        last_timestamp_seconds=120,
        now=now,
    )
    assert state.status == "reading"
    assert state.started_at == now
    assert state.progress_pct == 42

    apply_reader_state_update(state, status="finished", now=now)
    assert state.progress_pct == 100
    with pytest.raises(ValueError, match="finished -> later"):
        apply_reader_state_update(state, status="later", now=now)
    with pytest.raises(ValueError, match="between 0 and 100"):
        apply_reader_state_update(state, progress_pct=101, now=now)


def test_reader_state_schema_reuses_digest_lane_identity_and_local_uniqueness():
    table = Base.metadata.tables["reader_states"]
    foreign_keys = {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    unique_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    check_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    indexes = {index.name: index for index in table.indexes if isinstance(index, Index)}

    assert ("videos.id",) in foreign_keys
    assert ("digest_lanes.id",) in foreign_keys
    assert "uq_reader_states_lane_video" in unique_names
    assert "ck_reader_states_status" in check_names
    assert "ck_reader_states_progress_pct" in check_names
    assert indexes["uq_reader_states_local_video"].unique is True
    assert "digest_lane_id IS NULL" in str(
        indexes["uq_reader_states_local_video"].dialect_options["postgresql"]["where"]
    )


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value if isinstance(self.value, list) else []


class _ReaderDB:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []
        self.deleted = []
        self.commits = 0

    async def execute(self, _statement):
        return _Result(self.results.pop(0))

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1

    async def delete(self, value):
        self.deleted.append(value)


def _video_document(*, summary_content=None):
    video_id = uuid.uuid4()
    channel = Channel(id=uuid.uuid4(), youtube_channel_id="UCtest", name="Test Channel")
    video = Video(
        id=video_id,
        youtube_video_id="abc123",
        title="A readable transcript",
        url="https://www.youtube.com/watch?v=abc123",
        status="completed",
        duration_seconds=90,
    )
    video.channel = channel
    transcription = Transcription(
        id=uuid.uuid4(),
        video_id=video_id,
        full_text="A readable opening. A useful conclusion.",
        language="en",
        word_count=7,
    )
    transcription.segments = [
        TranscriptionSegment(
            segment_index=0,
            start_time=0,
            end_time=12,
            text="A readable opening.",
        ),
        TranscriptionSegment(
            segment_index=1,
            start_time=12,
            end_time=24,
            text="A useful conclusion.",
        ),
    ]
    video.transcription = transcription
    if summary_content is not None:
        video.summary = Summary(
            id=uuid.uuid4(),
            video_id=video_id,
            content=summary_content,
        )
    return video


def _client_with_db(db):
    app = create_app()

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_reader_document_api_creates_local_state_on_demand():
    video = _video_document()
    db = _ReaderDB(video, None)
    response = _client_with_db(db).get(f"/api/reader/videos/{video.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["video"]["id"] == str(video.id)
    assert body["transcription"]["block_count"] == 1
    assert body["state"]["status"] == "unread"
    assert body["state"]["resume_block_anchor"] == body["transcription"]["blocks"][0]["anchor"]
    assert len(db.added) == 1
    assert db.added[0].digest_lane_id is None
    assert db.commits == 1


def test_reader_page_is_summary_first_and_escapes_summary_markup():
    video = _video_document(summary_content="## Key point\nUseful signal.\n<script>alert(1)</script>")
    state = ReaderState(video_id=video.id, status="reading", progress_pct=35)
    response = _client_with_db(_ReaderDB(video, state)).get(f"/read/{video.id}")

    assert response.status_code == 200
    assert 'id="reader-summary-title"' in response.text
    assert "Useful signal." in response.text
    assert "<script>alert(1)</script>" not in response.text
    transcript_tag = response.text.split('id="reader-transcript-details"', 1)[1].split(">", 1)[0]
    assert "open" not in transcript_tag

    resumed = _client_with_db(_ReaderDB(video, state)).get(
        f"/read/{video.id}?resume=transcript"
    )
    resumed_tag = resumed.text.split('id="reader-transcript-details"', 1)[1].split(">", 1)[0]
    assert "open" in resumed_tag


def test_reader_state_api_updates_progress_without_pipeline_state():
    video = _video_document()
    blocks = build_reader_blocks(video.transcription.segments)
    state = ReaderState(video_id=video.id, status="unread", progress_pct=0)
    db = _ReaderDB(video, state)
    response = _client_with_db(db).patch(
        f"/api/reader/videos/{video.id}/state",
        json={
            "status": "reading",
            "progress_pct": 35,
            "last_block_anchor": blocks[0].anchor,
            "last_timestamp_seconds": 8,
        },
    )

    assert response.status_code == 200
    assert response.json()["progress_pct"] == 35
    assert video.status == "completed"
    assert db.commits == 1


def test_reader_state_api_rejects_invalid_input_and_transition():
    video = _video_document()
    client = _client_with_db(_ReaderDB())
    assert client.patch(
        f"/api/reader/videos/{video.id}/state", json={"progress_pct": 101}
    ).status_code == 422

    finished = ReaderState(video_id=video.id, status="finished", progress_pct=100)
    db = _ReaderDB(video, finished)
    response = _client_with_db(db).patch(
        f"/api/reader/videos/{video.id}/state", json={"status": "later"}
    )
    assert response.status_code == 409


def test_reader_mvp_has_semantic_blocks_controls_and_static_behavior():
    template = open("app/templates/reader_document.html", encoding="utf-8").read()
    script = open("app/static/js/reader.js", encoding="utf-8").read()
    css = open("app/static/css/reader-document.css", encoding="utf-8").read()

    assert '<article class="reader-article"' in template
    assert 'aria-label="Watch at' in template
    assert 'id="reader-search"' in template
    assert 'data-reader-status="later"' in template
    assert 'data-reader-status="finished"' in template
    assert 'id="reader-summary-title"' in template
    assert 'id="reader-transcript-details"' in template
    assert "{% if not summary_html or resume_transcript %}open{% endif %}" in template
    assert 'type="module" src="/static/js/reader.js?v=20260731"' in template
    assert "localStorage" in script
    assert "IntersectionObserver" in script
    assert "openTranscript" in script
    assert 'event.key.toLowerCase() === "j"' in script
    assert '@media (max-width: 699px)' in css
    assert "minmax(0, 1fr)" in css
    assert 'data-transcript-open="true"' in css


def test_outline_is_deterministic_and_time_based():
    from app.services.reader import build_reader_outline

    blocks = build_reader_blocks(
        [
            _segment(0, 0, 10, "Beginning."),
            _segment(1, 610, 620, "Ten minutes later."),
            _segment(2, 1210, 1220, "Twenty minutes later."),
        ],
        max_seconds=60,
    )
    outline = build_reader_outline(blocks)
    assert [item["label"] for item in outline] == ["Beginning", "Around 10 min", "Around 20 min"]


def test_annotations_reconcile_after_block_regeneration_and_export_safely():
    from app.services.reader_annotations import export_annotations_markdown, reconcile_annotation

    blocks = build_reader_blocks([_segment(0, 20, 30, "A durable selected passage appears here.")])
    annotation = ReaderAnnotation(
        id=uuid.uuid4(), video_id=uuid.uuid4(), annotation_type="note",
        block_anchor="old-anchor", start_timestamp_seconds=21, end_timestamp_seconds=22,
        start_offset=2, end_offset=18, selected_text_snapshot="selected passage",
        note_text="<script>alert(1)</script>", reconciliation_status="attached",
    )
    reconciled = reconcile_annotation(annotation, blocks)
    assert reconciled.block_anchor == blocks[0].anchor
    assert reconciled.status == "reattached"

    exported = export_annotations_markdown("Unsafe <title>", [annotation])
    assert "# Unsafe &lt;title&gt;" in exported
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in exported
    assert "<script>" not in exported


def test_annotation_schema_and_reader_ui_contract():
    table = Base.metadata.tables["reader_annotations"]
    check_names = {constraint.name for constraint in table.constraints if isinstance(constraint, CheckConstraint)}
    assert {"ck_reader_annotations_type", "ck_reader_annotations_timestamps", "ck_reader_annotations_offsets"} <= check_names

    template = open("app/templates/reader_document.html", encoding="utf-8").read()
    script = open("app/static/js/reader.js", encoding="utf-8").read()
    assert 'id="reader-selection-tools"' in template
    assert 'id="reader-annotation-list"' in template
    assert "createAnnotation" in script
    assert 'method: "DELETE"' in script


def test_reader_routes_expose_annotation_crud_export_and_highlights():
    paths = {
        (route.path, tuple(sorted(getattr(route, "methods", None) or [])))
        for route in create_app().routes
    }
    assert ("/api/reader/videos/{video_id}/annotations", ("GET",)) in paths
    assert ("/api/reader/videos/{video_id}/annotations", ("POST",)) in paths
    assert ("/api/reader/annotations/{annotation_id}", ("DELETE",)) in paths
    assert ("/api/reader/videos/{video_id}/annotations/export", ("GET",)) in paths
    assert any(path == "/read/highlights" for path, _methods in paths)


def test_annotation_api_validates_anchor_snapshot_and_persists_local_owner():
    video = _video_document()
    block = build_reader_blocks(video.transcription.segments)[0]
    selected = "readable opening"
    start = block.text.index(selected)
    payload = {
        "annotation_type": "highlight",
        "block_anchor": block.anchor,
        "start_timestamp_seconds": block.start_time,
        "end_timestamp_seconds": block.start_time,
        "start_offset": start,
        "end_offset": start + len(selected),
        "selected_text_snapshot": selected,
    }
    db = _ReaderDB(video)

    response = _client_with_db(db).post(
        f"/api/reader/videos/{video.id}/annotations", json=payload
    )

    assert response.status_code == 201
    assert db.added[0].digest_lane_id is None
    assert db.added[0].selected_text_snapshot == selected
    assert db.commits == 1

    mismatch = dict(payload, selected_text_snapshot="different text")
    mismatch_response = _client_with_db(_ReaderDB(video)).post(
        f"/api/reader/videos/{video.id}/annotations", json=mismatch
    )
    assert mismatch_response.status_code == 422


def test_annotation_export_escapes_persisted_text():
    video = _video_document()
    annotation = ReaderAnnotation(
        id=uuid.uuid4(),
        video_id=video.id,
        annotation_type="note",
        block_anchor="anchor",
        start_timestamp_seconds=5,
        end_timestamp_seconds=5,
        start_offset=0,
        end_offset=4,
        selected_text_snapshot="<b>claim</b>",
        note_text="<script>alert(1)</script>",
    )
    response = _client_with_db(_ReaderDB(video, [annotation])).get(
        f"/api/reader/videos/{video.id}/annotations/export"
    )

    assert response.status_code == 200
    assert "&lt;script&gt;" in response.text
    assert "<script>" not in response.text


def test_chapters_preserve_source_anchors_and_fall_back_deterministically():
    from app.services.reader_chapters import (
        chapter_source_fingerprint,
        deterministic_chapters,
        parse_semantic_chapter_response,
    )

    blocks = build_reader_blocks(
        [
            _segment(0, 0, 10, "Opening idea."),
            _segment(1, 620, 630, "A second topic."),
            _segment(2, 1240, 1250, "The conclusion."),
        ],
        max_seconds=60,
    )
    fallback = deterministic_chapters(blocks)

    assert [item["anchor"] for item in fallback] == [block.anchor for block in blocks]
    assert fallback[0]["end_time"] == blocks[1].start_time
    assert len(chapter_source_fingerprint(blocks)) == 64

    semantic = parse_semantic_chapter_response(
        f'```json\n[{{"title":"The premise","anchor":"{blocks[0].anchor}"}},'
        f'{{"title":"What changes","anchor":"{blocks[2].anchor}"}}]\n```',
        blocks,
    )
    assert semantic[0]["start_time"] == blocks[0].start_time
    assert semantic[0]["end_time"] == blocks[2].start_time
    with pytest.raises(ValueError, match="invalid"):
        parse_semantic_chapter_response(
            '[{"title":"Invented","anchor":"missing"}]', blocks
        )


def test_chapter_model_and_explicit_generation_ui_contract():
    table = Base.metadata.tables["reader_chapter_sets"]
    unique_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    template = open("app/templates/reader_document.html", encoding="utf-8").read()
    script = open("app/static/js/reader.js", encoding="utf-8").read()
    chapter_routes = [
        (route.path, tuple(sorted(route.methods or [])))
        for route in create_app().routes
        if route.path == "/api/reader/videos/{video_id}/chapters"
    ]

    assert "uq_reader_chapter_sets_video" in unique_names
    assert "data-generate-chapters" in template
    assert 'body: JSON.stringify({ mode: "semantic" })' in script
    assert chapter_routes == [
        ("/api/reader/videos/{video_id}/chapters", ("GET",)),
        ("/api/reader/videos/{video_id}/chapters", ("POST",)),
    ]


def test_semantic_chapter_generation_stores_provenance():
    video = _video_document()
    anchor = build_reader_blocks(video.transcription.segments)[0].anchor
    content = json.dumps([{"title": "A grounded chapter", "anchor": anchor}])
    db = _ReaderDB(video, None)
    with patch(
        "app.services.chat._call_anthropic",
        return_value={"content": content, "model": "test-model"},
    ):
        response = _client_with_db(db).post(
            f"/api/reader/videos/{video.id}/chapters", json={"mode": "semantic"}
        )

    assert response.status_code == 200
    assert response.json()["provenance"] == "semantic"
    assert response.json()["model"] == "test-model"
    assert db.added[0].source_fingerprint
    assert db.commits == 1


def test_semantic_chapter_provider_failure_falls_back_without_blocking_reader():
    video = _video_document()
    db = _ReaderDB(video, None)
    with patch("app.services.chat._call_anthropic", side_effect=RuntimeError("offline")):
        response = _client_with_db(db).post(
            f"/api/reader/videos/{video.id}/chapters", json={"mode": "semantic"}
        )

    assert response.status_code == 200
    assert response.json()["provenance"] == "deterministic"
    assert response.json()["fallback_reason"] == "RuntimeError"
    assert response.json()["chapters"]
