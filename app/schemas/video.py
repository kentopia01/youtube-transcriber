import uuid
from datetime import datetime

from pydantic import BaseModel, HttpUrl


class VideoSubmit(BaseModel):
    url: str


class VideoResponse(BaseModel):
    id: uuid.UUID
    youtube_video_id: str
    title: str
    url: str
    duration_seconds: float | None = None
    published_at: datetime | None = None
    thumbnail_url: str | None = None
    status: str
    error_message: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChannelSubmit(BaseModel):
    url: str


class ChannelVideoSelection(BaseModel):
    video_ids: list[str]


class JobResponse(BaseModel):
    id: uuid.UUID
    video_id: uuid.UUID | None = None
    channel_id: uuid.UUID | None = None
    job_type: str
    status: str
    progress_pct: float
    progress_message: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SearchQuery(BaseModel):
    query: str
    limit: int = 10


class SearchResult(BaseModel):
    video_id: uuid.UUID
    video_title: str
    chunk_text: str
    start_time: float | None = None
    end_time: float | None = None
    similarity: float
