import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.dependencies import get_db
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.schemas.chat import (
    ChatMessageOut,
    ChatMessageSend,
    ChatSessionCreate,
    ChatSessionDetail,
    ChatSessionOut,
    ChatSessionRename,
)
from app.services.chat import chat_with_context

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/sessions", response_model=ChatSessionOut)
async def create_session(
    data: ChatSessionCreate | None = None,
    db: AsyncSession = Depends(get_db),
):
    body = data or ChatSessionCreate()
    session = ChatSession(
        title=body.title,
        platform=body.platform,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/sessions", response_model=list[ChatSessionOut])
async def list_sessions(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChatSession)
        .order_by(ChatSession.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/sessions/{session_id}", response_model=ChatSessionDetail)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(selectinload(ChatSession.messages))
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.delete(session)
    await db.commit()
    return {"deleted": True, "session_id": str(session_id)}


@router.patch("/sessions/{session_id}", response_model=ChatSessionOut)
async def rename_session(
    session_id: uuid.UUID,
    data: ChatSessionRename,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.title = data.title
    await db.commit()
    await db.refresh(session)
    return session


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageOut)
async def send_message(
    session_id: uuid.UUID,
    data: ChatMessageSend,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Auto-generate title from first message
    if session.title is None:
        content_preview = data.content[:50]
        session.title = content_preview + ("..." if len(data.content) > 50 else "")

    # Save user message
    user_msg = ChatMessage(
        session_id=session.id,
        role="user",
        content=data.content,
    )
    db.add(user_msg)
    await db.flush()

    # Load only the last N messages (bounded query — avoids loading entire history)
    history_limit = settings.chat_max_history * 2
    recent = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(history_limit)
    )
    messages = list(reversed(recent.scalars().all()))

    # Build conversation history from recent messages
    history = [{"role": m.role, "content": m.content} for m in messages]

    # Call RAG chat service
    chat_result = await chat_with_context(
        question=data.content,
        history=history,
        db=db,
    )

    # Touch activity for any videos cited — keeps them out of the compression sweep.
    try:
        import uuid as _uuid
        from app.services.subscriptions import touch_video_activity
        for src in chat_result.get("sources", []):
            vid = src.get("video_id")
            if vid:
                await touch_video_activity(db, _uuid.UUID(vid))
    except Exception:  # noqa: BLE001
        pass

    # Save assistant message
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

    # Touch session updated_at
    session.updated_at = sa_func.now()
    await db.commit()
    await db.refresh(assistant_msg)

    return assistant_msg
