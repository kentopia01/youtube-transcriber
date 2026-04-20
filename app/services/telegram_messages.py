"""Message templates for Telegram push notifications.

Each renderer takes a ``payload`` dict and returns::

    {
      "text": str,
      "reply_markup": dict | None,   # Telegram InlineKeyboardMarkup
      "parse_mode": "Markdown" | "HTML" | None,
      "dedupe_key": str,             # for in-process dedupe (same key within
                                     # _DEDUPE_WINDOW_SECONDS is suppressed)
    }

Keep messages *short*. Telegram truncates; users scan.
"""

from __future__ import annotations

from typing import Any


class UnknownEvent(Exception):
    """Raised by a renderer to signal the event should be silently dropped."""


def _fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return ""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


def _button(text: str, callback_data: str) -> dict:
    return {"text": text, "callback_data": callback_data}


def _keyboard(rows: list[list[dict]]) -> dict:
    return {"inline_keyboard": rows}


def _render_video_completed(payload: dict) -> dict:
    title = (payload.get("title") or "Untitled")[:80]
    duration = _fmt_duration(payload.get("duration"))
    speakers = payload.get("speakers")
    video_id = payload.get("video_id")
    channel_id = payload.get("channel_id")

    meta_parts = []
    if duration:
        meta_parts.append(duration)
    if isinstance(speakers, int) and speakers > 0:
        meta_parts.append(f"{speakers} speaker{'s' if speakers != 1 else ''}")
    meta = ", ".join(meta_parts)
    meta_line = f"\n_{meta}_" if meta else ""

    text = f"✅ *Processed*\n{title}{meta_line}"

    buttons = []
    if video_id:
        buttons.append(_button("💬 Chat", f"video:chat:{video_id}"))
    if channel_id:
        buttons.append(_button("🎬 Channel", f"channel:open:{channel_id}"))

    return {
        "text": text,
        "reply_markup": _keyboard([buttons]) if buttons else None,
        "parse_mode": "Markdown",
        "dedupe_key": f"video_completed:{video_id}",
    }


def _render_video_failed(payload: dict) -> dict:
    title = (payload.get("title") or "Untitled")[:80]
    stage = payload.get("stage") or "unknown"
    reason = (payload.get("error_message") or "unknown")[:140]
    job_id = payload.get("job_id")

    text = f"❌ *Failed at `{stage}`*\n{title}\n`{reason}`"
    buttons = []
    if job_id:
        buttons.append(_button("🔁 Retry", f"job:retry:{job_id}"))

    return {
        "text": text,
        "reply_markup": _keyboard([buttons]) if buttons else None,
        "parse_mode": "Markdown",
        "dedupe_key": f"video_failed:{job_id}",
    }


def _render_persona_generated(payload: dict) -> dict:
    name = (payload.get("display_name") or "a channel")[:80]
    confidence = payload.get("confidence")
    channel_id = payload.get("channel_id")
    is_refresh = bool(payload.get("is_refresh"))

    icon = "♻️" if is_refresh else "✨"
    action_word = "refreshed" if is_refresh else "ready"
    conf = f" (confidence {confidence:.2f})" if isinstance(confidence, (int, float)) else ""
    text = f"{icon} *Persona {action_word}*: {name}{conf}"

    buttons = []
    if channel_id:
        buttons.append(_button("💬 Try it", f"persona:chat:{channel_id}"))

    return {
        "text": text,
        "reply_markup": _keyboard([buttons]) if buttons else None,
        "parse_mode": "Markdown",
        "dedupe_key": f"persona:{channel_id}:{action_word}",
    }


def _render_channel_queued(payload: dict) -> dict:
    name = (payload.get("channel_name") or "channel")[:80]
    count = payload.get("video_count") or 0
    channel_id = payload.get("channel_id")
    text = f"📥 *Queued*: {name} ({count} video{'s' if count != 1 else ''})"
    buttons = []
    if channel_id:
        buttons.append(_button("🎬 Open", f"channel:open:{channel_id}"))
    return {
        "text": text,
        "reply_markup": _keyboard([buttons]) if buttons else None,
        "parse_mode": "Markdown",
        "dedupe_key": f"channel_queued:{channel_id}",
    }


def _render_cost_threshold_80(payload: dict) -> dict:
    spent = float(payload.get("spent", 0.0))
    cap = float(payload.get("cap", 0.0))
    text = f"⚠️ *Daily LLM spend 80%*\n${spent:.2f} of ${cap:.2f}"
    return {
        "text": text,
        "reply_markup": None,
        "parse_mode": "Markdown",
        "dedupe_key": "cost_threshold_80",
    }


def _render_cost_threshold_100(payload: dict) -> dict:
    cap = float(payload.get("cap", 0.0))
    text = f"🛑 *Daily LLM budget exceeded* (${cap:.2f})"
    return {
        "text": text,
        "reply_markup": None,
        "parse_mode": "Markdown",
        "dedupe_key": "cost_threshold_100",
    }


def _render_digest_weekly(payload: dict) -> dict:
    text = payload.get("text")
    if not text:
        raise UnknownEvent("digest.weekly rendered empty")
    return {
        "text": text,
        "reply_markup": None,
        "parse_mode": "Markdown",
        "dedupe_key": str(payload.get("window_start", "weekly")),
    }


def _render_digest_morning(payload: dict) -> dict:
    """Chief-of-Staff morning brief. Body is already formatter-ready Markdown
    (bold + plain links). We convert to Telegram-safe HTML at send time."""
    text = payload.get("text")
    if not text:
        raise UnknownEvent("digest.morning rendered empty")
    from app.services.telegram_markdown import markdown_to_telegram_html

    header = "<b>🌅 Morning brief</b>\n\n"
    body_html = markdown_to_telegram_html(text)
    return {
        "text": header + body_html,
        "reply_markup": None,
        "parse_mode": "HTML",
        "dedupe_key": str(payload.get("window_start", "morning")),
    }


EVENT_RENDERERS: dict[str, Any] = {
    "video.completed": _render_video_completed,
    "video.failed": _render_video_failed,
    "persona.generated": _render_persona_generated,
    "persona.refreshed": _render_persona_generated,  # same shape
    "channel.queued": _render_channel_queued,
    "cost.threshold_80": _render_cost_threshold_80,
    "cost.threshold_100": _render_cost_threshold_100,
    "digest.weekly": _render_digest_weekly,
    "digest.morning": _render_digest_morning,
}
