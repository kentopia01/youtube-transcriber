import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ChatSessionCreate(BaseModel):
    title: str | None = None
    platform: str = "web"


class ChatSessionRename(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ChatMessageSend(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)
    channel_id: uuid.UUID | None = None
    video_id: uuid.UUID | None = None
    selection_text: str | None = Field(default=None, max_length=4000)
    selection_action: Literal["explain", "summarize", "context"] | None = None

    @model_validator(mode="after")
    def validate_selection_scope(self):
        if self.selection_action and not (self.selection_text or "").strip():
            raise ValueError("selection_text is required for a selection action")
        return self


class ChatSourceOut(BaseModel):
    video_id: str
    youtube_video_id: str | None = None
    video_title: str
    chunk_text: str
    start_time: float | None = None
    end_time: float | None = None
    similarity: float | None = None
    source_type: str | None = None


class ChatMessageOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    sources: list[ChatSourceOut] | None = None
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionOut(BaseModel):
    id: uuid.UUID
    title: str | None = None
    platform: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionDetail(ChatSessionOut):
    messages: list[ChatMessageOut] = []
