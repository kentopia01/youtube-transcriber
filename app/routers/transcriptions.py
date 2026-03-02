import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_db
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

    return {
        "id": str(transcription.id),
        "video_id": str(transcription.video_id),
        "full_text": transcription.full_text,
        "language": transcription.language,
        "model_size": transcription.model_size,
        "word_count": transcription.word_count,
        "processing_time_seconds": transcription.processing_time_seconds,
        "segments": [
            {
                "index": s.segment_index,
                "start": s.start_time,
                "end": s.end_time,
                "text": s.text,
                "confidence": s.confidence,
            }
            for s in transcription.segments
        ],
    }
