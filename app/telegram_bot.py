"""Telegram bot for chatting with video transcripts."""

import atexit
import fcntl
import os
from pathlib import Path

import structlog
from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
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
BOT_LOCK_PATH = Path("/tmp/yt-chatbot/app.lock")
_lock_handle = None


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
        "Send me a message to ask questions across your RAG-enabled videos.\n\n"
        "Chat:\n"
        "/new - Start a new chat session\n"
        "/sessions - List recent sessions\n"
        "/status - Library stats\n"
        "/videos - List RAG-enabled videos\n\n"
        "RAG controls:\n"
        "/ragstatus - Show all videos with on/off state\n"
        "/enable [keyword] - Enable RAG for matching videos (all if no keyword)\n"
        "/disable [keyword] - Disable RAG for matching videos\n"
        "/toggle [keyword] - Flip RAG state for matching videos\n\n"
        "Examples:\n"
        "  /enable agents\n"
        "  /disable podcast\n"
        "  /toggle security"
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
    if source.get("source_type") == "summary":
        return f"[\U0001f4f9 {title} Summary]"

    start = source.get("start_time")
    if start is not None:
        total = int(start)
        h, remainder = divmod(total, 3600)
        m, s = divmod(remainder, 60)
        ts = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        return f"[\U0001f4f9 {title} @ {ts}]"
    return f"[\U0001f4f9 {title}]"


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


def _release_bot_lock() -> None:
    global _lock_handle
    if _lock_handle is None:
        return
    try:
        _lock_handle.close()
    finally:
        _lock_handle = None


def acquire_bot_lock(lock_path: Path = BOT_LOCK_PATH) -> bool:
    """Ensure only one local polling bot instance runs at a time."""
    global _lock_handle
    if _lock_handle is not None:
        return True

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return False

    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    _lock_handle = handle
    atexit.register(_release_bot_lock)
    return True


async def telegram_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception(
        "telegram_update_error",
        error=str(context.error),
        update_type=type(update).__name__ if update is not None else None,
    )


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

        # Save user message
        user_msg = ChatMessage(
            session_id=session.id,
            role="user",
            content=user_text,
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

        # Build history
        history = [{"role": m.role, "content": m.content} for m in messages]

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
        logger.exception(
            "telegram_message_error",
            chat_id=chat_id,
            user_id=update.effective_user.id if update.effective_user else None,
            text_preview=user_text[:120],
        )
        await update.message.reply_text(
            "Sorry, an error occurred while processing your message. Please try again."
        )
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# RAG toggle helpers
# ---------------------------------------------------------------------------

def _fuzzy_match_videos(query: str, videos: list[Video]) -> list[Video]:
    """Return videos whose titles contain any word from query (case-insensitive)."""
    if not query:
        return []
    words = [w.lower() for w in query.split() if len(w) > 2]
    if not words:
        return []
    return [
        v for v in videos
        if any(w in (v.title or "").lower() for w in words)
    ]


async def ragstatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all videos with their RAG on/off status."""
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    db = await _get_db()
    try:
        result = await db.execute(
            select(Video)
            .where(Video.status == "completed")
            .order_by(Video.title)
            .limit(100)
        )
        videos = result.scalars().all()
        if not videos:
            await update.message.reply_text("No completed videos in library.")
            return
        on  = [v for v in videos if v.chat_enabled]
        off = [v for v in videos if not v.chat_enabled]
        lines = [f"RAG status — {len(on)} on / {len(off)} off\n"]
        if on:
            lines.append("✅ Enabled:")
            for v in on:
                lines.append(f"  • {v.title}")
        if off:
            lines.append("\n⬜ Disabled:")
            for v in off:
                lines.append(f"  • {v.title}")
        for chunk in split_message("\n".join(lines)):
            await update.message.reply_text(chunk)
    finally:
        await db.close()


async def _rag_set_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    enable: bool,
) -> None:
    """Shared logic for /enable and /disable."""
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    keyword = " ".join(context.args).strip() if context.args else ""
    db = await _get_db()
    try:
        result = await db.execute(
            select(Video).where(Video.status == "completed").order_by(Video.title)
        )
        all_videos = result.scalars().all()

        if keyword:
            matched = _fuzzy_match_videos(keyword, all_videos)
        else:
            matched = all_videos  # bulk apply to everything

        if not matched:
            await update.message.reply_text(
                f"No completed videos matched '{keyword}'.\nTip: use a few words from the title."
            )
            return

        changed = []
        for v in matched:
            if v.chat_enabled != enable:
                v.chat_enabled = enable
                changed.append(v.title)

        await db.commit()

        action = "enabled" if enable else "disabled"
        if not changed:
            titles = "\n".join(f"  • {v.title}" for v in matched)
            await update.message.reply_text(
                f"All {len(matched)} matched video(s) already {action}:\n{titles}"
            )
        else:
            titles = "\n".join(f"  • {t}" for t in changed)
            skipped = len(matched) - len(changed)
            msg = f"RAG {action} for {len(changed)} video(s):\n{titles}"
            if skipped:
                msg += f"\n\n({skipped} already {action}, skipped)"
            await update.message.reply_text(msg)
    finally:
        await db.close()


async def enable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/enable [keyword] — enable RAG for matching videos (all if no keyword)."""
    await _rag_set_command(update, context, enable=True)


async def disable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/disable [keyword] — disable RAG for matching videos (all if no keyword)."""
    await _rag_set_command(update, context, enable=False)


async def toggle_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/toggle [keyword] — flip RAG state for each matching video."""
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    keyword = " ".join(context.args).strip() if context.args else ""
    db = await _get_db()
    try:
        result = await db.execute(
            select(Video).where(Video.status == "completed").order_by(Video.title)
        )
        all_videos = result.scalars().all()
        matched = _fuzzy_match_videos(keyword, all_videos) if keyword else all_videos

        if not matched:
            await update.message.reply_text(
                f"No completed videos matched '{keyword}'."
            )
            return

        lines = [f"Toggled {len(matched)} video(s):"]
        for v in matched:
            v.chat_enabled = not v.chat_enabled
            state = "✅ on" if v.chat_enabled else "⬜ off"
            lines.append(f"  {state} — {v.title}")
        await db.commit()
        for chunk in split_message("\n".join(lines)):
            await update.message.reply_text(chunk)
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
    app.add_handler(CommandHandler("ragstatus", ragstatus_command))
    app.add_handler(CommandHandler("enable", enable_command))
    app.add_handler(CommandHandler("disable", disable_command))
    app.add_handler(CommandHandler("toggle", toggle_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(telegram_error_handler)

    return app


def run_bot() -> None:
    if not acquire_bot_lock():
        logger.warning("telegram_bot_already_running", lock_path=str(BOT_LOCK_PATH))
        return
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
