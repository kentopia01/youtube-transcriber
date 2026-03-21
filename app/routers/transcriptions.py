import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_db
from app.models.summary import Summary
from app.models.transcription import Transcription

router = APIRouter(prefix="/api/transcriptions", tags=["transcriptions"])


@router.get("/{video_id}")
async def get_transcription(video_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Transcription)
        .options(selectinload(Transcription.segments))
        .where(Transcription.video_id == video_id)
    )
    transcription = result.scalar_one_or_none()
    if not transcription:
        raise HTTPException(status_code=404, detail="Transcription not found")

    # Collect unique speakers from segments
    speakers = sorted(set(
        s.speaker for s in transcription.segments
        if s.speaker is not None
    ))

    # Fetch summary if it exists
    summary_result = await db.execute(
        select(Summary).where(Summary.video_id == video_id)
    )
    summary = summary_result.scalar_one_or_none()

    return {
        "id": str(transcription.id),
        "video_id": str(transcription.video_id),
        "full_text": transcription.full_text,
        "summary": summary.content if summary else None,
        "summary_model": summary.model if summary else None,
        "language": transcription.language,
        "language_detected": transcription.language,
        "model_size": transcription.model_size,
        "word_count": transcription.word_count,
        "processing_time_seconds": transcription.processing_time_seconds,
        "speakers": speakers,
        "diarization_enabled": len(speakers) > 0,
        "segments": [
            {
                "index": s.segment_index,
                "start": s.start_time,
                "end": s.end_time,
                "text": s.text,
                "confidence": s.confidence,
                "speaker": s.speaker,
            }
            for s in transcription.segments
        ],
    }
