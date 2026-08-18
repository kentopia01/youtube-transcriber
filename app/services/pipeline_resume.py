"""Artifact-aware pipeline resume planning shared by retry entry points."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import settings
from app.models.embedding_chunk import EmbeddingChunk
from app.models.summary import Summary
from app.models.transcription import Transcription
from app.models.video import Video
from app.services.pipeline_observability import build_artifact_check_result


def select_resume_stage(
    *,
    has_embeddings: bool,
    has_summary: bool,
    has_transcription: bool,
    has_audio: bool,
    diarization_requires_audio: bool,
) -> str:
    """Pick a resume stage only when that stage's required artifacts exist."""
    if has_embeddings and has_transcription:
        return "tasks.generate_embeddings"

    if has_summary and has_transcription:
        return "tasks.generate_embeddings"

    if has_transcription:
        if diarization_requires_audio:
            if has_audio:
                return "tasks.diarize_and_align"
            return "tasks.download_audio"
        return "tasks.cleanup_transcript"

    if has_audio:
        return "tasks.transcribe_audio"

    return "tasks.download_audio"


def _build_resume_result(video: Video, *, has_embeddings: bool, has_summary: bool, has_transcription: bool) -> tuple[str, dict[str, Any]]:
    audio_path = (video.audio_file_path or "").strip()
    has_audio = bool(audio_path and os.path.exists(audio_path))

    diarization_requires_audio = settings.inline_diarization_enabled
    # Cleanup mutates the persisted transcript in place, so the structured
    # Video.status is the durable proof that cleanup completed. Without this
    # branch, artifact-aware retries repeat cleanup instead of advancing.
    if has_transcription and video.status == "cleaned":
        selected_stage = "tasks.summarize_transcription"
    else:
        selected_stage = select_resume_stage(
            has_embeddings=has_embeddings,
            has_summary=has_summary,
            has_transcription=has_transcription,
            has_audio=has_audio,
            diarization_requires_audio=diarization_requires_audio,
        )
    artifact_check_result = build_artifact_check_result(
        has_embeddings=has_embeddings,
        has_summary=has_summary,
        has_transcription=has_transcription,
        has_audio=has_audio,
        diarization_requires_audio=diarization_requires_audio,
        selected_resume_stage=selected_stage,
    )
    return selected_stage, artifact_check_result


async def detect_resume_point_async(db: AsyncSession, video: Video) -> tuple[str, dict[str, Any]]:
    """Async artifact-aware resume planning for API retry requests."""
    video_id = video.id

    emb_result = await db.execute(
        select(EmbeddingChunk.id).where(EmbeddingChunk.video_id == video_id).limit(1)
    )
    has_embeddings = emb_result.scalar_one_or_none() is not None

    sum_result = await db.execute(select(Summary.id).where(Summary.video_id == video_id).limit(1))
    has_summary = sum_result.scalar_one_or_none() is not None

    tx_result = await db.execute(
        select(Transcription.id).where(Transcription.video_id == video_id).limit(1)
    )
    has_transcription = tx_result.scalar_one_or_none() is not None

    return _build_resume_result(
        video,
        has_embeddings=has_embeddings,
        has_summary=has_summary,
        has_transcription=has_transcription,
    )


def detect_resume_point_sync(db: Session, video: Video) -> tuple[str, dict[str, Any]]:
    """Sync artifact-aware resume planning for recovery scripts."""
    video_id = video.id
    has_embeddings = (
        db.query(EmbeddingChunk.id).filter(EmbeddingChunk.video_id == video_id).first()
        is not None
    )
    has_summary = db.query(Summary.id).filter(Summary.video_id == video_id).first() is not None
    has_transcription = (
        db.query(Transcription.id).filter(Transcription.video_id == video_id).first()
        is not None
    )

    return _build_resume_result(
        video,
        has_embeddings=has_embeddings,
        has_summary=has_summary,
        has_transcription=has_transcription,
    )
