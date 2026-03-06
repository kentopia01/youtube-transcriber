"""Telegram bot for chatting with video transcripts."""

import structlog
from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import settings
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.video import Video
from app.services.chat import chat_with_context

logger = structlog.get_logger()

# Database session factory using the native (non-Docker) URL
_engine = create_async_engine(settings.database_url_native, echo=False)
_async_session = async_sessionmaker(_engine, expire_on_commit=False)

TELEGRAM_MESSAGE_LIMIT = 4096


def _is_user_allowed(user_id: int) -> bool:
    if not settings.telegram_allowed_users:
        return True
    return user_id in settings.telegram_allowed_users


DENIED_TEXT = "Sorry, you are not authorized to use this bot."


async def _get_db() -> AsyncSession:
    return _async_session()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    await update.message.reply_text(
        "Welcome to the YouTube Transcriber Chat Bot!\n\n"
        "Send me a message to ask questions about your video transcript library.\n\n"
        "Commands:\n"
        "/new - Start a new chat session\n"
        "/sessions - List recent sessions\n"
        "/status - Show library stats\n"
        "/videos - List chat-enabled videos"
    )


async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    chat_id = update.effective_chat.id
    db = await _get_db()
    try:
        session = ChatSession(
            title=None,
            platform="telegram",
            telegram_chat_id=chat_id,
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        await update.message.reply_text(
            f"New chat session created.\nSession ID: {session.id}\n\n"
            "Send me your question!"
        )
    finally:
        await db.close()


async def sessions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    chat_id = update.effective_chat.id
    db = await _get_db()
    try:
        result = await db.execute(
            select(ChatSession)
            .where(
                ChatSession.platform == "telegram",
                ChatSession.telegram_chat_id == chat_id,
            )
            .order_by(ChatSession.updated_at.desc())
            .limit(10)
        )
        sessions = result.scalars().all()
        if not sessions:
            await update.message.reply_text("No sessions found. Send a message to start chatting!")
            return
        lines = ["Recent sessions:\n"]
        for s in sessions:
            title = s.title or "(untitled)"
            lines.append(f"- {title}\n  {s.created_at:%Y-%m-%d %H:%M}")
        await update.message.reply_text("\n".join(lines))
    finally:
        await db.close()


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    db = await _get_db()
    try:
        total_result = await db.execute(select(sa_func.count(Video.id)))
        total = total_result.scalar() or 0
        enabled_result = await db.execute(
            select(sa_func.count(Video.id)).where(Video.chat_enabled.is_(True))
        )
        enabled = enabled_result.scalar() or 0
        await update.message.reply_text(
            f"Library status:\n"
            f"- Chat-enabled videos: {enabled}\n"
            f"- Total videos: {total}"
        )
    finally:
        await db.close()


async def videos_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    db = await _get_db()
    try:
        result = await db.execute(
            select(Video.title)
            .where(Video.chat_enabled.is_(True))
            .order_by(Video.title)
            .limit(50)
        )
        titles = result.scalars().all()
        if not titles:
            await update.message.reply_text("No chat-enabled videos found.")
            return
        lines = [f"Chat-enabled videos ({len(titles)}):\n"]
        for t in titles:
            lines.append(f"- {t}")
        text = "\n".join(lines)
        for chunk in split_message(text):
            await update.message.reply_text(chunk)
    finally:
        await db.close()


def _format_source_citation(source: dict) -> str:
    title = source.get("video_title", "Unknown")
    start = source.get("start_time")
    if start is not None:
        total = int(start)
        h, remainder = divmod(total, 3600)
        m, s = divmod(remainder, 60)
        ts = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        return f"[{title} @ {ts}]"
    return f"[{title}]"


def format_response_with_sources(content: str, sources: list[dict]) -> str:
    if not sources:
        return content
    seen = set()
    citations = []
    for src in sources:
        citation = _format_source_citation(src)
        if citation not in seen:
            seen.add(citation)
            citations.append(citation)
    if citations:
        source_text = "\n".join(citations[:5])
        return f"{content}\n\nSources:\n{source_text}"
    return content


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        # Try to split at a newline near the limit
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1 or split_at < limit // 2:
            # Fall back to splitting at a space
            split_at = text.rfind(" ", 0, limit)
        if split_at == -1 or split_at < limit // 2:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return

    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text:
        return

    db = await _get_db()
    try:
        # Find the most recent session for this chat
        result = await db.execute(
            select(ChatSession)
            .where(
                ChatSession.platform == "telegram",
                ChatSession.telegram_chat_id == chat_id,
            )
            .order_by(ChatSession.updated_at.desc())
            .limit(1)
        )
        session = result.scalars().first()

        # Auto-create session if none exists
        if session is None:
            session = ChatSession(
                title=None,
                platform="telegram",
                telegram_chat_id=chat_id,
            )
            db.add(session)
            await db.flush()

        # Auto-title from first message
        if session.title is None:
            preview = user_text[:50]
            session.title = preview + ("..." if len(user_text) > 50 else "")

        # Load messages for history
        result = await db.execute(
            select(ChatSession)
            .where(ChatSession.id == session.id)
            .options(selectinload(ChatSession.messages))
        )
        session = result.scalar_one()

        # Save user message
        user_msg = ChatMessage(
            session_id=session.id,
            role="user",
            content=user_text,
        )
        db.add(user_msg)
        await db.flush()

        # Build history
        history = [
            {"role": m.role, "content": m.content}
            for m in session.messages
        ]

        # Call RAG chat
        chat_result = await chat_with_context(
            question=user_text,
            history=history,
            db=db,
        )

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

        session.updated_at = sa_func.now()
        await db.commit()

        # Format and send response
        response_text = format_response_with_sources(
            chat_result["content"], chat_result["sources"]
        )
        for chunk in split_message(response_text):
            await update.message.reply_text(chunk)

    except Exception:
        logger.exception("telegram_message_error")
        await update.message.reply_text(
            "Sorry, an error occurred while processing your message. Please try again."
        )
    finally:
        await db.close()


def create_bot_application() -> Application:
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not configured")

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("new", new_command))
    app.add_handler(CommandHandler("sessions", sessions_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("videos", videos_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app


def run_bot() -> None:
    app = create_bot_application()
    logger.info("telegram_bot_starting")
    app.run_polling()


if __name__ == "__main__":
    import logging

    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    run_bot()
