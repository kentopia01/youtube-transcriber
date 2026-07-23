from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_db
from app.config import settings
from app.models.reader_state import READER_STATUS_UNREAD, ReaderState
from app.models.reader_annotation import ReaderAnnotation
from app.models.reader_chapter_set import ReaderChapterSet
from app.models.transcription import Transcription
from app.models.video import Video
from app.models.channel import Channel
from app.models.reader_state import READER_STATUSES
from app.schemas.inventory import ReaderStateInventoryItem, ReaderStateInventoryPage
from app.services.reader import (
    apply_reader_state_update,
    build_reader_blocks,
    reader_state_dict,
)
from app.services.reader_annotations import (
    annotation_dict,
    export_annotations_markdown,
    reconcile_annotation,
)
from app.services.reader_chapters import (
    GENERATOR_VERSION,
    chapter_source_fingerprint,
    deterministic_chapters,
    parse_semantic_chapter_response,
    semantic_chapter_prompt,
)


router = APIRouter(prefix="/api/reader", tags=["reader"])


class ReaderStatePatch(BaseModel):
    status: Literal["unread", "reading", "later", "finished", "archived"] | None = None
    progress_pct: float | None = Field(default=None, ge=0, le=100)
    last_block_anchor: str | None = Field(default=None, min_length=1, max_length=96)
    last_timestamp_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_change(self):
        if all(
            value is None
            for value in (
                self.status,
                self.progress_pct,
                self.last_block_anchor,
                self.last_timestamp_seconds,
            )
        ):
            raise ValueError("At least one reader state field is required")
        return self


class AnnotationCreate(BaseModel):
    annotation_type: Literal["highlight", "note", "bookmark"]
    block_anchor: str = Field(min_length=1, max_length=96)
    start_timestamp_seconds: float = Field(ge=0)
    end_timestamp_seconds: float = Field(ge=0)
    start_offset: int = Field(default=0, ge=0)
    end_offset: int = Field(default=0, ge=0)
    selected_text_snapshot: str = Field(default="", max_length=4000)
    note_text: str | None = Field(default=None, max_length=10000)
    context_before: str | None = Field(default=None, max_length=240)
    context_after: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def validate_range_and_content(self):
        if self.end_timestamp_seconds < self.start_timestamp_seconds:
            raise ValueError("end timestamp must not precede start timestamp")
        if self.end_offset < self.start_offset:
            raise ValueError("end offset must not precede start offset")
        if self.annotation_type in {"highlight", "note"} and not self.selected_text_snapshot.strip():
            raise ValueError("selected text is required for highlights and notes")
        if self.annotation_type == "note" and not (self.note_text or "").strip():
            raise ValueError("note text is required for notes")
        return self


class AnnotationPatch(BaseModel):
    annotation_type: Literal["highlight", "note", "bookmark"] | None = None
    note_text: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def require_change(self):
        if self.annotation_type is None and self.note_text is None:
            raise ValueError("At least one annotation field is required")
        return self


class ChapterGenerateRequest(BaseModel):
    mode: Literal["semantic", "deterministic"] = "semantic"


@router.get("/states", response_model=ReaderStateInventoryPage)
async def list_reader_states(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    if status and status not in READER_STATUSES:
        raise HTTPException(status_code=422, detail="Unknown reader status")
    filters = [ReaderState.digest_lane_id.is_(None)]
    if status:
        filters.append(ReaderState.status == status)
    total = int(await db.scalar(select(func.count(ReaderState.id)).where(*filters)) or 0)
    rows = (
        await db.execute(
            select(ReaderState, Video, Channel)
            .join(Video, Video.id == ReaderState.video_id)
            .outerjoin(Channel, Channel.id == Video.channel_id)
            .where(*filters)
            .order_by(
                ReaderState.last_read_at.desc().nullslast(),
                ReaderState.updated_at.desc(),
                ReaderState.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return ReaderStateInventoryPage(
        items=[
            ReaderStateInventoryItem(
                id=state.id,
                video_id=video.id,
                video_title=video.title,
                youtube_video_id=video.youtube_video_id,
                channel_name=channel.name if channel else None,
                status=state.status,
                progress_pct=state.progress_pct,
                last_block_anchor=state.last_block_anchor,
                last_timestamp_seconds=state.last_timestamp_seconds,
                last_read_at=state.last_read_at,
                updated_at=state.updated_at,
            )
            for state, video, channel in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


async def _load_video_document(db: AsyncSession, video_id: uuid.UUID) -> tuple[Video, list]:
    result = await db.execute(
        select(Video)
        .options(
            selectinload(Video.channel),
            selectinload(Video.transcription).selectinload(Transcription.segments),
        )
        .where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if not video.transcription:
        raise HTTPException(status_code=404, detail="Transcript not found")
    blocks = build_reader_blocks(
        video.transcription.segments,
        full_text=video.transcription.full_text,
        duration_seconds=video.duration_seconds,
    )
    if not blocks:
        raise HTTPException(status_code=422, detail="Transcript has no readable content")
    return video, blocks


async def _get_local_state(db: AsyncSession, video_id: uuid.UUID) -> ReaderState | None:
    result = await db.execute(
        select(ReaderState).where(
            ReaderState.video_id == video_id,
            ReaderState.digest_lane_id.is_(None),
        )
    )
    return result.scalar_one_or_none()


def _document_response(video: Video, blocks: list, state: ReaderState) -> dict:
    transcription = video.transcription
    total_words = sum(block.word_count for block in blocks)
    return {
        "video": {
            "id": str(video.id),
            "youtube_video_id": video.youtube_video_id,
            "title": video.title,
            "channel_id": str(video.channel_id) if video.channel_id else None,
            "channel_name": video.channel.name if video.channel else None,
            "duration_seconds": video.duration_seconds,
            "thumbnail_url": video.thumbnail_url,
            "url": video.url,
        },
        "transcription": {
            "id": str(transcription.id),
            "language": transcription.language,
            "word_count": transcription.word_count or total_words,
            "estimated_reading_minutes": max(1, round(total_words / 225)),
            "block_count": len(blocks),
            "blocks": [block.to_dict() for block in blocks],
        },
        "state": reader_state_dict(state, blocks),
    }


@router.get("/videos/{video_id}")
async def get_reader_document(video_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    video, blocks = await _load_video_document(db, video_id)
    state = await _get_local_state(db, video_id)
    now = datetime.now(UTC)
    if state is None:
        state = ReaderState(
            video_id=video_id,
            digest_lane_id=None,
            status=READER_STATUS_UNREAD,
            progress_pct=0.0,
        )
        db.add(state)
    state.last_read_at = now
    video.last_activity_at = now
    await db.commit()
    return _document_response(video, blocks, state)


@router.patch("/videos/{video_id}/state")
async def update_reader_state(
    video_id: uuid.UUID,
    patch: ReaderStatePatch,
    db: AsyncSession = Depends(get_db),
):
    video, blocks = await _load_video_document(db, video_id)
    anchors = {block.anchor for block in blocks}
    if patch.last_block_anchor is not None and patch.last_block_anchor not in anchors:
        raise HTTPException(status_code=422, detail="Unknown transcript block anchor")
    if (
        patch.last_timestamp_seconds is not None
        and video.duration_seconds is not None
        and patch.last_timestamp_seconds > video.duration_seconds + 30
    ):
        raise HTTPException(status_code=422, detail="Timestamp exceeds video duration")

    state = await _get_local_state(db, video_id)
    if state is None:
        state = ReaderState(
            video_id=video_id,
            digest_lane_id=None,
            status=READER_STATUS_UNREAD,
            progress_pct=0.0,
        )
        db.add(state)
    try:
        apply_reader_state_update(
            state,
            status=patch.status,
            progress_pct=patch.progress_pct,
            last_block_anchor=patch.last_block_anchor,
            last_timestamp_seconds=patch.last_timestamp_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    video.last_activity_at = state.last_read_at
    await db.commit()
    return reader_state_dict(state, blocks)


@router.get("/videos/{video_id}/annotations")
async def list_annotations(video_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    _video, blocks = await _load_video_document(db, video_id)
    result = await db.execute(
        select(ReaderAnnotation)
        .where(
            ReaderAnnotation.video_id == video_id,
            ReaderAnnotation.digest_lane_id.is_(None),
        )
        .order_by(ReaderAnnotation.start_timestamp_seconds, ReaderAnnotation.created_at)
    )
    annotations = result.scalars().all()
    return [annotation_dict(item, reconcile_annotation(item, blocks)) for item in annotations]


def _chapter_payload(
    *, chapters: list[dict], provenance: str, fingerprint: str,
    model: str | None = None, fallback_reason: str | None = None,
) -> dict:
    return {
        "chapters": chapters,
        "provenance": provenance,
        "generator_version": GENERATOR_VERSION,
        "model": model,
        "source_fingerprint": fingerprint,
        "fallback_reason": fallback_reason,
    }


@router.get("/videos/{video_id}/chapters")
async def get_chapters(video_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    _video, blocks = await _load_video_document(db, video_id)
    fingerprint = chapter_source_fingerprint(blocks)
    result = await db.execute(
        select(ReaderChapterSet).where(ReaderChapterSet.video_id == video_id)
    )
    chapter_set = result.scalar_one_or_none()
    if chapter_set and chapter_set.source_fingerprint == fingerprint:
        return _chapter_payload(
            chapters=chapter_set.chapters,
            provenance=chapter_set.provenance,
            fingerprint=fingerprint,
            model=chapter_set.model,
            fallback_reason=chapter_set.fallback_reason,
        )
    return _chapter_payload(
        chapters=deterministic_chapters(blocks),
        provenance="deterministic",
        fingerprint=fingerprint,
        fallback_reason="not_generated" if chapter_set is None else "transcript_changed",
    )


@router.post("/videos/{video_id}/chapters")
async def generate_chapters(
    video_id: uuid.UUID,
    payload: ChapterGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    _video, blocks = await _load_video_document(db, video_id)
    fingerprint = chapter_source_fingerprint(blocks)
    chapters = deterministic_chapters(blocks)
    provenance = "deterministic"
    model = None
    fallback_reason = "operator_requested"
    if payload.mode == "semantic":
        try:
            from app.services.chat import _call_anthropic

            result = await asyncio.to_thread(
                _call_anthropic,
                "You create grounded transcript chapter titles and return strict JSON only.",
                [{"role": "user", "content": semantic_chapter_prompt(blocks)}],
                settings.chat_model,
            )
            chapters = parse_semantic_chapter_response(result["content"], blocks)
            provenance = "semantic"
            model = result.get("model")
            fallback_reason = None
        except Exception as exc:  # noqa: BLE001 - safe deterministic degradation
            fallback_reason = exc.__class__.__name__[:128]

    existing_result = await db.execute(
        select(ReaderChapterSet).where(ReaderChapterSet.video_id == video_id)
    )
    chapter_set = existing_result.scalar_one_or_none()
    if chapter_set is None:
        chapter_set = ReaderChapterSet(video_id=video_id)
        db.add(chapter_set)
    chapter_set.chapters = chapters
    chapter_set.provenance = provenance
    chapter_set.generator_version = GENERATOR_VERSION
    chapter_set.model = model
    chapter_set.source_fingerprint = fingerprint
    chapter_set.fallback_reason = fallback_reason
    chapter_set.updated_at = datetime.now(UTC)
    await db.commit()
    return _chapter_payload(
        chapters=chapters,
        provenance=provenance,
        fingerprint=fingerprint,
        model=model,
        fallback_reason=fallback_reason,
    )


@router.post("/videos/{video_id}/annotations", status_code=201)
async def create_annotation(
    video_id: uuid.UUID,
    payload: AnnotationCreate,
    db: AsyncSession = Depends(get_db),
):
    video, blocks = await _load_video_document(db, video_id)
    block = next((item for item in blocks if item.anchor == payload.block_anchor), None)
    if block is None:
        raise HTTPException(status_code=422, detail="Unknown transcript block anchor")
    if payload.end_offset > len(block.text):
        raise HTTPException(status_code=422, detail="Annotation offset exceeds block text")
    if payload.annotation_type in {"highlight", "note"}:
        anchored_text = block.text[payload.start_offset : payload.end_offset]
        if anchored_text != payload.selected_text_snapshot.strip():
            raise HTTPException(
                status_code=422,
                detail="Selected text does not match the transcript offsets",
            )
    if video.duration_seconds and payload.end_timestamp_seconds > video.duration_seconds + 30:
        raise HTTPException(status_code=422, detail="Annotation timestamp exceeds video duration")
    annotation = ReaderAnnotation(
        video_id=video_id,
        digest_lane_id=None,
        annotation_type=payload.annotation_type,
        block_anchor=payload.block_anchor,
        start_timestamp_seconds=payload.start_timestamp_seconds,
        end_timestamp_seconds=payload.end_timestamp_seconds,
        start_offset=payload.start_offset,
        end_offset=payload.end_offset,
        selected_text_snapshot=payload.selected_text_snapshot.strip(),
        note_text=payload.note_text.strip() if payload.note_text else None,
        context_before=payload.context_before,
        context_after=payload.context_after,
        reconciliation_status="attached",
    )
    db.add(annotation)
    video.last_activity_at = datetime.now(UTC)
    await db.commit()
    return annotation_dict(annotation)


async def _local_annotation(db: AsyncSession, annotation_id: uuid.UUID) -> ReaderAnnotation:
    result = await db.execute(
        select(ReaderAnnotation).where(
            ReaderAnnotation.id == annotation_id,
            ReaderAnnotation.digest_lane_id.is_(None),
        )
    )
    annotation = result.scalar_one_or_none()
    if annotation is None:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return annotation


@router.patch("/annotations/{annotation_id}")
async def update_annotation(
    annotation_id: uuid.UUID,
    payload: AnnotationPatch,
    db: AsyncSession = Depends(get_db),
):
    annotation = await _local_annotation(db, annotation_id)
    next_type = payload.annotation_type or annotation.annotation_type
    next_note = (
        payload.note_text.strip() or None
        if payload.note_text is not None
        else annotation.note_text
    )
    if next_type in {"highlight", "note"} and not annotation.selected_text_snapshot:
        raise HTTPException(status_code=409, detail="This annotation has no selected passage")
    if next_type == "note" and not next_note:
        raise HTTPException(status_code=409, detail="A note requires note text")
    annotation.annotation_type = next_type
    annotation.note_text = next_note
    annotation.updated_at = datetime.now(UTC)
    await db.commit()
    return annotation_dict(annotation)


@router.delete("/annotations/{annotation_id}", status_code=204)
async def delete_annotation(annotation_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    annotation = await _local_annotation(db, annotation_id)
    await db.delete(annotation)
    await db.commit()


@router.get("/videos/{video_id}/annotations/export", response_class=PlainTextResponse)
async def export_annotations(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    video_result = await db.execute(select(Video).where(Video.id == video_id))
    video = video_result.scalar_one_or_none()
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    result = await db.execute(
        select(ReaderAnnotation)
        .where(
            ReaderAnnotation.video_id == video_id,
            ReaderAnnotation.digest_lane_id.is_(None),
        )
        .order_by(ReaderAnnotation.start_timestamp_seconds, ReaderAnnotation.created_at)
    )
    content = export_annotations_markdown(video.title, result.scalars().all())
    return PlainTextResponse(
        content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="annotations-{video_id}.md"'},
    )
