import uuid
from datetime import datetime

from pydantic import BaseModel


class ChatSessionCreate(BaseModel):
    title: str | None = None
    platform: str = "web"


class ChatSessionRename(BaseModel):
    title: str


class ChatMessageSend(BaseModel):
    content: str


class ChatSourceOut(BaseModel):
    video_id: str
    video_title: str
    chunk_text: str
    start_time: float | None = None
    end_time: float | None = None
    similarity: float | None = None


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
