"""Telegram bot for chatting with video transcripts."""

import atexit
import dataclasses
import fcntl
import os
from pathlib import Path

import structlog
from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import settings
from app.models.channel import Channel
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.persona import Persona
from app.models.video import Video
from app.services.chat import chat_with_context
from app.services.persona import (
    SCOPE_CHANNEL,
    compose_persona_system_prompt,
    get_exemplar_chunks,
    get_persona,
)

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
        "/videos - List RAG-enabled videos\n"
        "/channels - List channels with ready personas\n"
        "/ask_channel <name> <question> - Ask a specific channel persona\n\n"
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


async def _resolve_channel_for_persona(
    db: AsyncSession, query: str
) -> tuple[Channel | None, Persona | None]:
    """Find a channel whose name or persona display_name matches ``query``.

    Case-insensitive. Exact match > prefix > substring.
    Returns ``(channel, persona)`` or ``(None, None)``.
    """
    import uuid as _uuid

    q = query.strip().lower()
    if not q:
        return None, None

    persona_rows = (
        await db.execute(
            select(Persona).where(Persona.scope_type == SCOPE_CHANNEL)
        )
    ).scalars().all()
    if not persona_rows:
        return None, None

    channels = (
        await db.execute(
            select(Channel).where(
                Channel.id.in_([_uuid.UUID(p.scope_id) for p in persona_rows])
            )
        )
    ).scalars().all()
    channel_by_id = {str(c.id): c for c in channels}

    best: tuple[Channel, Persona] | None = None
    best_score = -1
    for p in persona_rows:
        ch = channel_by_id.get(p.scope_id)
        if ch is None:
            continue
        dn = (p.display_name or "").lower()
        cn = (ch.name or "").lower()
        if q in (dn, cn):
            score = 100
        elif dn.startswith(q) or cn.startswith(q):
            score = 50
        elif q in dn or q in cn:
            score = 20
        else:
            score = 0
        if score > best_score:
            best_score = score
            best = (ch, p)

    if best is None or best_score <= 0:
        return None, None
    return best


async def channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List channels that have a persona ready."""
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    db = await _get_db()
    try:
        persona_rows = (await db.execute(
            select(Persona).where(Persona.scope_type == SCOPE_CHANNEL).order_by(Persona.generated_at.desc())
        )).scalars().all()
        if not persona_rows:
            await update.message.reply_text(
                "No channel personas yet. They build automatically once a channel has "
                f"{settings.persona_min_videos} completed videos."
            )
            return
        channel_ids = [p.scope_id for p in persona_rows]
        import uuid as _uuid
        channels = (await db.execute(
            select(Channel).where(Channel.id.in_([_uuid.UUID(cid) for cid in channel_ids]))
        )).scalars().all()
        by_id = {str(c.id): c for c in channels}

        lines = ["Channels with personas:\n"]
        for p in persona_rows:
            ch = by_id.get(p.scope_id)
            label = p.display_name or (ch.name if ch else p.scope_id)
            lines.append(f"• {label} (confidence {p.confidence:.2f})")
        lines.append("\nAsk one: /ask_channel <name> <question>")
        await update.message.reply_text("\n".join(lines))
    finally:
        await db.close()


async def ask_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """One-off question to a channel persona: /ask_channel <name_substring> <question>."""
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /ask_channel <channel name or keyword> <question>\n"
            "Example: /ask_channel AllIn what did they say about AI valuations?\n"
            "Tip: /channels lists available personas."
        )
        return

    # First token is the channel matcher; rest is the question
    query = args[0]
    question = " ".join(args[1:]).strip()
    if not question:
        await update.message.reply_text("Please include a question after the channel name.")
        return

    db = await _get_db()
    try:
        channel, persona = await _resolve_channel_for_persona(db, query)
        if channel is None or persona is None:
            await update.message.reply_text(
                f"No channel persona matches '{query}'. Use /channels to see options."
            )
            return

        exemplars = await get_exemplar_chunks(db, persona)
        system_prompt = compose_persona_system_prompt(persona)

        chat_result = await chat_with_context(
            question=question,
            history=[],
            db=db,
            channel_id=channel.id,
            system_prompt=system_prompt,
            exemplar_chunks=exemplars,
        )

        header = f"💬 {persona.display_name}\n\n"
        body = chat_result["content"]
        for chunk in split_message(header + body):
            await update.message.reply_text(chunk)
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Phase A: feature-parity commands
# ---------------------------------------------------------------------------


def _api_headers() -> dict[str, str]:
    if settings.api_key:
        return {"X-API-Key": settings.api_key}
    return {}


async def submit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Submit a YouTube video or channel URL. Auto-detects which."""
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: /submit <YouTube video or channel URL>"
        )
        return
    url = args[0].strip()

    import httpx
    from app.services.youtube import is_channel_url as _is_channel

    endpoint = "/api/channels" if _is_channel(url) else "/api/videos"
    async with httpx.AsyncClient(
        base_url=settings.internal_web_base_url, timeout=45.0
    ) as client:
        try:
            resp = await client.post(endpoint, json={"url": url}, headers=_api_headers())
        except httpx.HTTPError as exc:
            await update.message.reply_text(f"❌ Network error: {exc}")
            return

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail") or resp.text
        except Exception:
            detail = resp.text
        await update.message.reply_text(f"❌ {detail}")
        return

    body = resp.json()
    if endpoint == "/api/videos":
        job_id = body.get("job_id", "n/a")
        video_id = body.get("video_id", "n/a")
        status = body.get("status", "queued")
        await update.message.reply_text(
            f"📥 Video {status}\njob_id: {job_id}\nvideo_id: {video_id}\n\nI'll ping you when it's done."
        )
    else:
        cname = body.get("channel_name") or body.get("name") or "channel"
        total = body.get("total_videos") or body.get("discovered") or "?"
        await update.message.reply_text(
            f"📥 Channel '{cname}' queued ({total} videos)."
        )


async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show running and recently failed jobs."""
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    from app.models.job import Job
    from app.models.video import Video

    db = await _get_db()
    try:
        running = (
            await db.execute(
                select(Job, Video)
                .join(Video, Video.id == Job.video_id, isouter=True)
                .where(Job.status.in_(["running", "queued", "pending"]))
                .order_by(Job.created_at.desc())
                .limit(10)
            )
        ).all()
        failed = (
            await db.execute(
                select(Job, Video)
                .join(Video, Video.id == Job.video_id, isouter=True)
                .where(Job.status == "failed", Job.manual_review_required.is_(True))
                .order_by(Job.created_at.desc())
                .limit(5)
            )
        ).all()

        lines = []
        if running:
            lines.append("*Active:*")
            for job, video in running:
                title = (video.title or "?")[:50] if video else "?"
                stage = job.current_stage or "queued"
                pct = int(job.progress_pct or 0)
                lines.append(f"• {stage} {pct}% — {title}")
        else:
            lines.append("No active jobs.")
        if failed:
            lines.append("\n*Needs attention:*")
            for job, video in failed:
                title = (video.title or "?")[:50] if video else "?"
                reason = (job.error_message or "unknown")[:80]
                lines.append(f"• ❌ {title}\n   {reason}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    finally:
        await db.close()


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hybrid search across the library."""
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("Usage: /search <query>")
        return
    query = " ".join(args).strip()

    import httpx

    async with httpx.AsyncClient(
        base_url=settings.internal_web_base_url, timeout=30.0
    ) as client:
        try:
            resp = await client.post(
                "/api/search", json={"query": query}, headers=_api_headers()
            )
        except httpx.HTTPError as exc:
            await update.message.reply_text(f"❌ Search error: {exc}")
            return

    if resp.status_code >= 400:
        await update.message.reply_text(f"❌ Search failed: {resp.text[:200]}")
        return

    results = (resp.json() or {}).get("results", [])[:5]
    if not results:
        await update.message.reply_text(f"No results for '{query}'.")
        return

    out = [f"🔎 *Results for* '{query}':\n"]
    for i, r in enumerate(results, 1):
        title = (r.get("video_title") or "?")[:80]
        ts = ""
        if r.get("start_time") is not None:
            s = int(r["start_time"])
            ts = f" @ {s // 60}:{s % 60:02d}"
        snippet = (r.get("chunk_text") or "")[:180].replace("\n", " ")
        out.append(f"[{i}] *{title}*{ts}\n{snippet}…")
    await update.message.reply_text("\n\n".join(out), parse_mode="Markdown")


async def ask_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask a question scoped to a single video matched by title keyword."""
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /ask_video <title keyword> <question>"
        )
        return
    keyword = args[0]
    question = " ".join(args[1:]).strip()
    if not question:
        await update.message.reply_text("Please include a question.")
        return

    db = await _get_db()
    try:
        # Find best video by title substring
        rows = (
            await db.execute(
                select(Video)
                .where(Video.status == "completed")
                .order_by(Video.published_at.desc().nullslast())
            )
        ).scalars().all()
        q = keyword.lower()
        match = next(
            (v for v in rows if q in (v.title or "").lower()),
            None,
        )
        if match is None:
            await update.message.reply_text(
                f"No completed video matches '{keyword}'."
            )
            return

        # Bump activity so this video stays out of compression sweep
        try:
            from app.services.subscriptions import touch_video_activity
            await touch_video_activity(db, match.id)
        except Exception:
            pass

        # Reuse chat_with_context with a channel_id=None; filter chunks manually
        # by calling semantic_search scoped to this video's channel, then
        # restricting chunks whose video_id matches.
        from app.services.embedding import SUMMARY_SPEAKER_LABEL
        from app.services.search import encode_query, semantic_search

        query_embedding = encode_query(question)
        chunks = await semantic_search(
            db,
            query_embedding=query_embedding,
            limit=settings.chat_retrieval_top_k * 3,
            query=question,
            channel_id=match.channel_id,
            chat_enabled_only=True,
        )
        chunks = [c for c in chunks if str(c.get("video_id")) == str(match.id)][
            : settings.chat_retrieval_top_k
        ]

        if not chunks:
            await update.message.reply_text(
                f"Found '{match.title}' but couldn't retrieve relevant excerpts."
            )
            return

        # Lightweight direct chat call — bypass chat_with_context so we can
        # use the already-retrieved chunks.
        from app.services.chat import SYSTEM_PROMPT, _call_anthropic, _format_chunks_for_context

        context_text = _format_chunks_for_context(chunks)
        messages = [
            {
                "role": "user",
                "content": (
                    f"Context from the video '{match.title}':\n\n"
                    f"{context_text}\n\nQuestion: {question}"
                ),
            }
        ]

        import asyncio
        from functools import partial

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            partial(_call_anthropic, SYSTEM_PROMPT, messages, settings.anthropic_chat_model),
        )

        header = f"🎬 {match.title[:80]}\n\n"
        for chunk in split_message(header + result["content"]):
            await update.message.reply_text(chunk)
    finally:
        await db.close()


async def refresh_persona_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Force-rebuild a channel's persona."""
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: /refresh_persona <channel name or keyword>"
        )
        return
    query = args[0]

    db = await _get_db()
    try:
        channel, persona = await _resolve_channel_for_persona(db, query)
        if channel is None:
            await update.message.reply_text(
                f"No channel persona matches '{query}'. Use /channels to see options."
            )
            return
        from app.tasks.generate_persona import enqueue_channel_persona

        enqueue_channel_persona(str(channel.id), forced=True)
        await update.message.reply_text(
            f"♻️ Queued persona rebuild for {channel.name}. I'll ping you when it's ready."
        )
    finally:
        await db.close()


async def cost_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Today / month-to-date LLM spend vs daily budget."""
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    from datetime import datetime, timezone
    from app.models.llm_usage import LlmUsage as LLMUsage

    db = await _get_db()
    try:
        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        today_total = float(
            (
                await db.execute(
                    select(sa_func.coalesce(sa_func.sum(LLMUsage.estimated_cost_usd), 0.0)).where(
                        LLMUsage.created_at >= start_of_day
                    )
                )
            ).scalar()
            or 0.0
        )
        month_total = float(
            (
                await db.execute(
                    select(sa_func.coalesce(sa_func.sum(LLMUsage.estimated_cost_usd), 0.0)).where(
                        LLMUsage.created_at >= start_of_month
                    )
                )
            ).scalar()
            or 0.0
        )

        budget = settings.daily_llm_budget_usd
        pct = int((today_total / budget) * 100) if budget > 0 else 0
        bar_filled = min(20, pct // 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)

        lines = [
            "💰 *LLM spend*",
            f"Today: ${today_total:.2f} / ${budget:.2f} ({pct}%)",
            f"`{bar}`",
            f"Month-to-date: ${month_total:.2f}",
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    finally:
        await db.close()


# --- Notification preferences ---


def _notify_state_path() -> "Path":
    return Path(settings.telegram_notify_state_path)


def _read_notify_state() -> dict:
    p = _notify_state_path()
    if not p.exists():
        return {
            "enabled": settings.telegram_notify_enabled,
            "muted_events": list(settings.telegram_notify_muted_events),
        }
    try:
        import json

        return json.loads(p.read_text())
    except Exception:
        return {
            "enabled": settings.telegram_notify_enabled,
            "muted_events": list(settings.telegram_notify_muted_events),
        }


def _write_notify_state(state: dict) -> None:
    import json

    p = _notify_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2))


NOTIFY_EVENTS_ALL = [
    "video.completed",
    "video.failed",
    "persona.generated",
    "persona.refreshed",
    "channel.queued",
    "cost.threshold_80",
    "cost.threshold_100",
    "digest.weekly",
]


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Subscribe to a channel for nightly auto-ingest."""
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: /subscribe <YouTube channel URL or handle>\n"
            "Example: /subscribe https://youtube.com/@lexfridman"
        )
        return
    url = args[0].strip()

    import httpx

    async with httpx.AsyncClient(
        base_url=settings.internal_web_base_url, timeout=30.0
    ) as client:
        try:
            resp = await client.post(
                "/api/subscriptions", json={"url": url}, headers=_api_headers()
            )
        except httpx.HTTPError as exc:
            await update.message.reply_text(f"❌ Network error: {exc}")
            return

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail") or resp.text
        except Exception:
            detail = resp.text
        await update.message.reply_text(f"❌ {detail}")
        return

    body = resp.json()
    await update.message.reply_text(
        f"✅ Subscribed to *{body.get('channel_name', 'channel')}*.\n"
        f"Polling every {body.get('poll_frequency_hours', 24)}h, "
        f"up to {body.get('max_videos_per_poll', 3)} videos per poll.",
        parse_mode="Markdown",
    )


async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable a subscription by channel name keyword."""
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("Usage: /unsubscribe <channel name or keyword>")
        return
    query = " ".join(args).strip()

    db = await _get_db()
    try:
        from app.services.subscriptions import (
            disable_subscription,
            resolve_channel_by_query,
        )

        channel = await resolve_channel_by_query(db, query)
        if channel is None:
            await update.message.reply_text(
                f"No channel matches '{query}'. Try /subscriptions."
            )
            return
        sub = await disable_subscription(db, channel.id, reason="user_disabled")
        if sub is None:
            await update.message.reply_text(
                f"'{channel.name}' is not subscribed."
            )
            return
        await update.message.reply_text(
            f"🔕 Unsubscribed from *{channel.name}*.", parse_mode="Markdown"
        )
    finally:
        await db.close()


async def subscriptions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List active subscriptions and their state."""
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    db = await _get_db()
    try:
        from app.services.subscriptions import list_subscriptions

        subs = await list_subscriptions(db)
        if not subs:
            await update.message.reply_text(
                "No subscriptions. Add one with /subscribe <channel url>."
            )
            return
        enabled = [s for s in subs if s.enabled]
        disabled = [s for s in subs if not s.enabled]
        lines = [f"📡 *Subscriptions* ({len(enabled)} active, {len(disabled)} disabled)\n"]
        for s in enabled:
            name = s.channel.name if s.channel else str(s.channel_id)
            last = s.last_polled_at.strftime("%b %d %H:%M") if s.last_polled_at else "never"
            lines.append(
                f"• ✅ {name[:40]} — every {s.poll_frequency_hours}h, last {last}"
                + (f", {s.videos_ingested_today}/{s.max_videos_per_poll} today" if s.videos_ingested_today else "")
            )
        if disabled:
            lines.append("\n*Disabled:*")
            for s in disabled:
                name = s.channel.name if s.channel else str(s.channel_id)
                reason = (s.disabled_reason or "user")[:40]
                lines.append(f"• ⏸ {name[:40]} — {reason}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    finally:
        await db.close()


async def notify_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/notify [on|off|status] [event_type]"""
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return
    args = context.args or []
    state = _read_notify_state()

    if not args or args[0] == "status":
        enabled = state.get("enabled", True)
        muted = state.get("muted_events", [])
        lines = [
            f"🔔 Notifications: *{'on' if enabled else 'off'}*",
            f"Events: {len(NOTIFY_EVENTS_ALL) - len(muted)}/{len(NOTIFY_EVENTS_ALL)} active",
        ]
        if muted:
            lines.append("Muted: " + ", ".join(muted))
        lines.append("\nToggle: /notify on|off\nPer event: /notify off <event>")
        lines.append("Events: " + ", ".join(NOTIFY_EVENTS_ALL))
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    action = args[0].lower()
    if action not in ("on", "off"):
        await update.message.reply_text("Usage: /notify on|off|status [event]")
        return

    if len(args) == 1:
        state["enabled"] = action == "on"
        _write_notify_state(state)
        await update.message.reply_text(
            f"🔔 Notifications turned *{action}*.", parse_mode="Markdown"
        )
        return

    event = args[1]
    if event not in NOTIFY_EVENTS_ALL:
        await update.message.reply_text(
            f"Unknown event '{event}'. Valid: {', '.join(NOTIFY_EVENTS_ALL)}"
        )
        return
    muted = set(state.get("muted_events", []))
    if action == "off":
        muted.add(event)
    else:
        muted.discard(event)
    state["muted_events"] = sorted(muted)
    _write_notify_state(state)
    await update.message.reply_text(
        f"🔔 '{event}' {'muted' if action == 'off' else 'enabled'}."
    )


# ---------------------------------------------------------------------------
# Command manifest + /help
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class BotCmd:
    name: str
    group: str
    short: str
    args: str | None
    handler: object


def _cmd(name, group, short, handler, args=None):
    return BotCmd(name=name, group=group, short=short, args=args, handler=handler)


def _build_command_manifest() -> list[BotCmd]:
    return [
        _cmd("start", "Getting started", "Welcome + entry point", start_command),
        _cmd("help", "Getting started", "Show all commands", help_command),

        _cmd("submit", "Content", "Submit a YouTube URL (video or channel)", submit_command, args="<url>"),
        _cmd("queue", "Content", "Active + failed jobs", queue_command),
        _cmd("search", "Content", "Semantic search across the library", search_command, args="<query>"),

        _cmd("new", "Chat", "Start a new chat session", new_command),
        _cmd("sessions", "Chat", "Recent chat sessions", sessions_command),
        _cmd("channels", "Chat", "List channels with ready personas", channels_command),
        _cmd("ask_channel", "Chat", "Ask a channel in its own voice", ask_channel_command, args="<channel> <question>"),
        _cmd("ask_video", "Chat", "Ask about a specific video", ask_video_command, args="<title keyword> <question>"),
        _cmd("refresh_persona", "Chat", "Rebuild a channel persona", refresh_persona_command, args="<channel>"),

        _cmd("status", "Library", "Library size stats", status_command),
        _cmd("videos", "Library", "List RAG-enabled videos", videos_command),
        _cmd("ragstatus", "Library", "All videos with RAG state", ragstatus_command),
        _cmd("enable", "Library", "Enable RAG for videos", enable_command, args="[keyword]"),
        _cmd("disable", "Library", "Disable RAG for videos", disable_command, args="[keyword]"),
        _cmd("toggle", "Library", "Flip RAG state", toggle_command, args="[keyword]"),

        _cmd("subscribe", "Content", "Subscribe to a channel for nightly auto-ingest", subscribe_command, args="<channel_url>"),
        _cmd("unsubscribe", "Content", "Stop auto-ingesting from a channel", unsubscribe_command, args="<channel>"),
        _cmd("subscriptions", "Content", "List active subscriptions", subscriptions_command),

        _cmd("cost", "Admin", "Today / month LLM spend vs budget", cost_command),
        _cmd("notify", "Admin", "Toggle push notifications", notify_command, args="on|off|status [event]"),
    ]


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Auto-generated command reference."""
    if not _is_user_allowed(update.effective_user.id):
        await update.message.reply_text(DENIED_TEXT)
        return

    manifest = _build_command_manifest()
    by_group: dict[str, list[BotCmd]] = {}
    for c in manifest:
        by_group.setdefault(c.group, []).append(c)

    lines = ["*YouTube Transcriber Bot*\n"]
    for group in ("Getting started", "Content", "Chat", "Library", "Admin"):
        cmds = by_group.get(group, [])
        if not cmds:
            continue
        lines.append(f"\n*{group}*")
        for c in cmds:
            usage = f"/{c.name}"
            if c.args:
                usage += f" `{c.args}`"
            lines.append(f"• {usage} — {c.short}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Phase C: inline action-button callbacks
# ---------------------------------------------------------------------------


async def callback_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispatch a callback_query press to the right handler.

    Callback data format: ``domain:action:arg``. Currently:
      - ``video:chat:<video_id>``       — open a chat session scoped to the video's channel
      - ``video:open:<video_id>``       — reply with a short video summary
      - ``channel:open:<channel_id>``   — reply with channel persona status + chat link
      - ``job:retry:<job_id>``          — POST /api/jobs/{id}/retry
      - ``persona:chat:<channel_id>``   — shortcut to /ask_channel pattern
      - ``persona:refresh:<channel_id>``— trigger /refresh_persona
    """
    query = update.callback_query
    if query is None:
        return
    user = query.from_user
    if user is None or not _is_user_allowed(user.id):
        await query.answer("Unauthorized", show_alert=True)
        return

    data = query.data or ""
    parts = data.split(":", 2)
    if len(parts) < 3:
        await query.answer("Invalid action.")
        return
    domain, action, arg = parts

    # Acknowledge the tap immediately so the spinner on the user's side stops.
    try:
        await query.answer()
    except Exception:  # noqa: BLE001
        pass

    try:
        if domain == "video" and action == "chat":
            await _cb_video_chat(query, arg)
        elif domain == "video" and action == "open":
            await _cb_video_open(query, arg)
        elif domain == "channel" and action == "open":
            await _cb_channel_open(query, arg)
        elif domain == "job" and action == "retry":
            await _cb_job_retry(query, arg)
        elif domain == "persona" and action == "chat":
            await _cb_persona_chat(query, arg)
        elif domain == "persona" and action == "refresh":
            await _cb_persona_refresh(query, arg)
        else:
            await query.message.reply_text(f"Unknown action: {data}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("callback_handler_failed", data=data, error=str(exc))
        await query.message.reply_text(f"⚠️ Action failed: {exc}")


async def _cb_video_open(query, video_id: str) -> None:
    db = await _get_db()
    try:
        video = await db.get(Video, __import__("uuid").UUID(video_id))
        if video is None:
            await query.message.reply_text("Video not found.")
            return
        duration = ""
        if video.duration_seconds:
            s = int(video.duration_seconds)
            h, rem = divmod(s, 3600)
            m, sec = divmod(rem, 60)
            duration = f" ({h}h {m}m)" if h else f" ({m}m {sec}s)"
        text = (
            f"🎬 *{video.title[:100]}*{duration}\n"
            f"status: `{video.status}`"
        )
        if video.url:
            text += f"\n{video.url}"
        await query.message.reply_text(text, parse_mode="Markdown")
    finally:
        await db.close()


async def _cb_video_chat(query, video_id: str) -> None:
    db = await _get_db()
    try:
        video = await db.get(Video, __import__("uuid").UUID(video_id))
        if video is None:
            await query.message.reply_text("Video not found.")
            return
        keyword = (video.title or "").split()[0][:16] if video.title else video_id[:8]
        await query.message.reply_text(
            f"Ask about '{(video.title or video_id)[:60]}' with:\n"
            f"/ask_video {keyword} <your question>"
        )
    finally:
        await db.close()


async def _cb_channel_open(query, channel_id: str) -> None:
    db = await _get_db()
    try:
        import uuid as _uuid
        channel = await db.get(Channel, _uuid.UUID(channel_id))
        if channel is None:
            await query.message.reply_text("Channel not found.")
            return
        persona = await get_persona(db, SCOPE_CHANNEL, channel_id)
        lines = [f"🎬 *{channel.name}*", f"videos: {channel.video_count}"]
        if persona:
            lines.append(
                f"persona: *{persona.display_name}* (conf {persona.confidence:.2f})"
            )
            lines.append(f"Chat: `/ask_channel {channel.name.split()[0][:16]} <question>`")
        else:
            lines.append("persona: not yet built")
        await query.message.reply_text("\n".join(lines), parse_mode="Markdown")
    finally:
        await db.close()


async def _cb_job_retry(query, job_id: str) -> None:
    import httpx

    async with httpx.AsyncClient(
        base_url=settings.internal_web_base_url, timeout=20.0
    ) as client:
        try:
            resp = await client.post(f"/api/jobs/{job_id}/retry", headers=_api_headers())
        except httpx.HTTPError as exc:
            await query.message.reply_text(f"❌ Retry network error: {exc}")
            return
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail") or resp.text
        except Exception:
            detail = resp.text
        await query.message.reply_text(f"❌ Retry failed: {detail}")
    else:
        await query.message.reply_text(f"🔁 Retry queued for job `{job_id}`.", parse_mode="Markdown")


async def _cb_persona_chat(query, channel_id: str) -> None:
    db = await _get_db()
    try:
        import uuid as _uuid
        persona = await get_persona(db, SCOPE_CHANNEL, channel_id)
        if persona is None:
            await query.message.reply_text("This channel does not have a persona yet.")
            return
        channel = await db.get(Channel, _uuid.UUID(channel_id))
        name = persona.display_name or (channel.name if channel else channel_id)
        keyword = name.split()[0][:16]
        await query.message.reply_text(
            f"Ask {name} with:\n/ask_channel {keyword} <your question>"
        )
    finally:
        await db.close()


async def _cb_persona_refresh(query, channel_id: str) -> None:
    from app.tasks.generate_persona import enqueue_channel_persona

    enqueue_channel_persona(str(channel_id), forced=True)
    await query.message.reply_text(
        f"♻️ Queued persona rebuild. I'll ping you when it's ready."
    )


def create_bot_application() -> Application:
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not configured")

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init_register_commands)
        .build()
    )

    for cmd in _build_command_manifest():
        app.add_handler(CommandHandler(cmd.name, cmd.handler))
    app.add_handler(CallbackQueryHandler(callback_dispatcher))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(telegram_error_handler)

    return app


async def _post_init_register_commands(application: Application) -> None:
    """Register commands with Telegram so the native / menu shows them."""
    from telegram import BotCommand

    commands = [
        BotCommand(c.name, c.short) for c in _build_command_manifest()
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("telegram_commands_registered", count=len(commands))
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram_set_my_commands_failed", error=str(exc))


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
