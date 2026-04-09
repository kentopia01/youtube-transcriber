import re
import uuid
from datetime import datetime

from pydantic import BaseModel, HttpUrl, field_validator


class ChatToggle(BaseModel):
    enabled: bool


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
    limit: int | None = None
    after_date: str | None = None
    before_date: str | None = None
    min_duration: int | None = None
    max_duration: int | None = None

    @field_validator("limit")
    @classmethod
    def limit_must_be_positive(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("limit must be >= 1")
        return v

    @field_validator("after_date", "before_date")
    @classmethod
    def date_must_be_valid(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError("date must be in YYYY-MM-DD format")
        return v

    @field_validator("min_duration", "max_duration")
    @classmethod
    def duration_must_be_non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("duration must be >= 0")
        return v


class ChannelVideoSelection(BaseModel):
    video_ids: list[str] = []
    latest: int | None = None

    @field_validator("latest")
    @classmethod
    def latest_must_be_positive(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("latest must be >= 1")
        return v


class JobResponse(BaseModel):
    id: uuid.UUID
    video_id: uuid.UUID | None = None
    channel_id: uuid.UUID | None = None
    job_type: str
    status: str
    lifecycle_status: str | None = None
    attempt_state: str | None = None
    current_stage: str | None = None
    stage_updated_at: datetime | None = None
    last_activity_at: datetime | None = None
    progress_pct: float
    progress_message: str | None = None
    error_message: str | None = None
    failure_signature_count: int = 0
    recovery_status: str | None = None
    recovery_reason: str | None = None
    manual_review_required: bool = False
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
