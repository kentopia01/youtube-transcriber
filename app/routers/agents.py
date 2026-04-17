"""Persona-agent chat endpoints.

v1: channel personas only. Sessions are tied to a persona via
``chat_sessions.persona_id``. Message handling reuses
``app.services.chat.chat_with_context`` with a persona-specific system prompt
and a ``channel_id`` filter on retrieval.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.dependencies import get_db
from app.models.channel import Channel
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.schemas.chat import (
    ChatMessageOut,
    ChatMessageSend,
    ChatSessionDetail,
    ChatSessionOut,
)
from app.services.chat import chat_with_context
from app.services.persona import (
    SCOPE_CHANNEL,
    compose_persona_system_prompt,
    get_exemplar_chunks,
    get_persona,
)

router = APIRouter(prefix="/api/agents", tags=["agents"])


# ---------------------------------------------------------------------------
# Channel personas
# ---------------------------------------------------------------------------


async def _load_channel_persona(db: AsyncSession, channel_id: uuid.UUID):
    """Return (channel, persona). 404 if either missing."""
    channel = await db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    persona = await get_persona(db, SCOPE_CHANNEL, str(channel_id))
    if persona is None:
        raise HTTPException(
            status_code=409,
            detail="This channel does not have a persona yet. Wait for ingestion to complete or trigger generation via POST /api/channels/{id}/generate-persona.",
        )
    return channel, persona


@router.post("/channel/{channel_id}/sessions", response_model=ChatSessionOut)
async def create_channel_session(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Open a new chat session bound to this channel's persona."""
    channel, persona = await _load_channel_persona(db, channel_id)
    session = ChatSession(
        platform="web",
        persona_id=persona.id,
        title=f"{persona.display_name}: new chat",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/channel/{channel_id}/sessions", response_model=list[ChatSessionOut])
async def list_channel_sessions(
    channel_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    _channel, persona = await _load_channel_persona(db, channel_id)
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.persona_id == persona.id)
        .order_by(ChatSession.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/channel/{channel_id}/sessions/{session_id}", response_model=ChatSessionDetail)
async def get_channel_session(
    channel_id: uuid.UUID,
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    _channel, persona = await _load_channel_persona(db, channel_id)
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.id == session_id, ChatSession.persona_id == persona.id)
        .options(selectinload(ChatSession.messages))
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found for this channel")
    return session


@router.post(
    "/channel/{channel_id}/sessions/{session_id}/messages",
    response_model=ChatMessageOut,
)
async def send_channel_message(
    channel_id: uuid.UUID,
    session_id: uuid.UUID,
    data: ChatMessageSend,
    db: AsyncSession = Depends(get_db),
):
    channel, persona = await _load_channel_persona(db, channel_id)

    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.persona_id == persona.id
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found for this channel")

    if session.title is None or session.title.endswith(": new chat"):
        preview = data.content.strip()[:50]
        session.title = (
            f"{persona.display_name}: {preview}{'…' if len(data.content.strip()) > 50 else ''}"
        )

    user_msg = ChatMessage(
        session_id=session.id,
        role="user",
        content=data.content,
    )
    db.add(user_msg)
    await db.flush()

    history_limit = settings.chat_max_history * 2
    recent = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(history_limit)
    )
    messages = list(reversed(recent.scalars().all()))
    history = [{"role": m.role, "content": m.content} for m in messages]

    exemplars = await get_exemplar_chunks(db, persona)
    system_prompt = compose_persona_system_prompt(persona)

    chat_result = await chat_with_context(
        question=data.content,
        history=history,
        db=db,
        channel_id=channel.id,
        system_prompt=system_prompt,
        exemplar_chunks=exemplars,
    )

    try:
        import uuid as _uuid
        from app.services.subscriptions import touch_video_activity
        for src in chat_result.get("sources", []):
            vid = src.get("video_id")
            if vid:
                await touch_video_activity(db, _uuid.UUID(vid))
    except Exception:  # noqa: BLE001
        pass

    assistant_msg = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=chat_result["content"],
        sources=chat_result["sources"],
        model=chat_result["model"],
        prompt_tokens=chat_result["prompt_tokens"],
        completion_tokens=chat_result["completion_tokens"],
    )
    db.add(assistant_msg)

    session.updated_at = sa_func.now()
    await db.commit()
    await db.refresh(assistant_msg)

    return assistant_msg
