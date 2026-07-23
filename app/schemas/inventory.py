from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class JobInventoryItem(BaseModel):
    id: uuid.UUID
    video_id: uuid.UUID | None
    video_title: str | None
    youtube_video_id: str | None
    channel_id: uuid.UUID | None
    job_type: str
    status: str
    current_stage: str | None
    progress_pct: float
    attempt_number: int
    attempt_creation_reason: str | None
    error_message: str | None
    hidden_from_queue: bool
    created_at: datetime
    completed_at: datetime | None


class JobInventoryPage(BaseModel):
    items: list[JobInventoryItem]
    total: int
    limit: int
    offset: int


class VideoInventoryItem(BaseModel):
    id: uuid.UUID
    youtube_video_id: str
    channel_id: uuid.UUID | None
    channel_name: str | None
    title: str
    status: str
    duration_seconds: float | None
    published_at: datetime | None
    thumbnail_url: str | None
    has_transcript: bool
    reader_status: str
    reader_progress_pct: float
    dismissed_at: datetime | None
    created_at: datetime


class VideoInventoryPage(BaseModel):
    items: list[VideoInventoryItem]
    total: int
    limit: int
    offset: int


class ReaderStateInventoryItem(BaseModel):
    id: uuid.UUID
    video_id: uuid.UUID
    video_title: str
    youtube_video_id: str
    channel_name: str | None
    status: str
    progress_pct: float
    last_block_anchor: str | None
    last_timestamp_seconds: float | None
    last_read_at: datetime | None
    updated_at: datetime


class ReaderStateInventoryPage(BaseModel):
    items: list[ReaderStateInventoryItem]
    total: int
    limit: int
    offset: int
