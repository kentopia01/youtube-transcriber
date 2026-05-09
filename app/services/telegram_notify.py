"""Source-agnostic push notifier for the Telegram bot.

A single owner consumes events from any part of the system (web routers,
Celery tasks, cron jobs). This module is a thin wrapper around Telegram's
``sendMessage`` / ``sendDocument`` HTTP endpoints — no dependence on the
``python-telegram-bot`` framework so Celery workers can call it without an
event loop.

Fire-and-forget semantics: every failure is caught and logged. Nothing
raises from ``notify`` into caller code.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import structlog

from app.config import settings
from app.services.telegram_messages import EVENT_RENDERERS, UnknownEvent

logger = structlog.get_logger()


# In-process dedupe: (event_type, dedupe_key) -> last-sent unix ts
_DEDUPE: dict[tuple[str, str], float] = {}
_DEDUPE_LOCK = threading.Lock()
_DEDUPE_WINDOW_SECONDS = 60.0


def _load_state() -> dict:
    """Read notification preferences from the on-disk state file."""
    p = Path(settings.telegram_notify_state_path)
    if not p.exists():
        return {
            "enabled": settings.telegram_notify_enabled,
            "muted_events": list(settings.telegram_notify_muted_events),
        }
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001 — best-effort
        return {
            "enabled": settings.telegram_notify_enabled,
            "muted_events": list(settings.telegram_notify_muted_events),
        }


def _should_send(event_type: str) -> bool:
    state = _load_state()
    if not state.get("enabled", True):
        return False
    return event_type not in state.get("muted_events", [])


def _primary_chat_id() -> int | None:
    """Return the first allowlisted user id (solo-user bot)."""
    users = settings.telegram_allowed_users or []
    if not users:
        return None
    return int(users[0])


def _dedupe_allow(event_type: str, dedupe_key: str) -> bool:
    """Return True if this event hasn't been sent within the dedupe window."""
    now = time.time()
    key = (event_type, dedupe_key)
    with _DEDUPE_LOCK:
        last = _DEDUPE.get(key)
        if last is not None and now - last < _DEDUPE_WINDOW_SECONDS:
            return False
        _DEDUPE[key] = now
        # Opportunistic cleanup
        if len(_DEDUPE) > 500:
            cutoff = now - _DEDUPE_WINDOW_SECONDS * 2
            for k, ts in list(_DEDUPE.items()):
                if ts < cutoff:
                    _DEDUPE.pop(k, None)
    return True


def _send(
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
    parse_mode: str | None = "Markdown",
) -> bool:
    """POST sendMessage. Short timeout, all failures swallowed."""
    import requests  # local import so tests can import this module without the dep

    token = settings.telegram_bot_token
    if not token:
        logger.debug("telegram_notify_no_token")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)

    try:
        resp = requests.post(url, data=payload, timeout=2.5)
        if getattr(resp, "ok", True) is False:
            logger.warning(
                "telegram_notify_send_failed",
                status_code=getattr(resp, "status_code", None),
                text=getattr(resp, "text", "")[:200],
            )
            return False
        return True
    except Exception as exc:  # noqa: BLE001 — fire-and-forget
        logger.warning("telegram_notify_send_failed", error=str(exc))
        return False


def _send_document(
    chat_id: int,
    text: str,
    document_path: str,
    *,
    filename: str | None = None,
    mime_type: str | None = None,
    reply_markup: dict | None = None,
    parse_mode: str | None = "Markdown",
) -> bool:
    """POST sendDocument with a local file attachment."""
    import requests  # local import so tests can import this module without the dep

    token = settings.telegram_bot_token
    if not token:
        logger.debug("telegram_notify_no_token")
        return False

    path = Path(document_path)
    if not path.exists() or not path.is_file():
        logger.warning("telegram_notify_document_missing", path=str(path))
        return False

    url = f"https://api.telegram.org/bot{token}/sendDocument"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "caption": text,
        "disable_content_type_detection": False,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)

    try:
        with path.open("rb") as fh:
            files = {
                "document": (
                    filename or path.name,
                    fh,
                    mime_type or "application/octet-stream",
                )
            }
            resp = requests.post(url, data=payload, files=files, timeout=10.0)
        if getattr(resp, "ok", True) is False:
            logger.warning(
                "telegram_notify_document_send_failed",
                status_code=getattr(resp, "status_code", None),
                text=getattr(resp, "text", "")[:200],
            )
            return False
        return True
    except Exception as exc:  # noqa: BLE001 — fire-and-forget
        logger.warning("telegram_notify_document_send_failed", error=str(exc), path=str(path))
        return False


def notify(event_type: str, payload: dict | None = None) -> bool:
    """Fire-and-forget push notification.

    Never raises. Silent no-op when the event is muted, the bot isn't
    configured, the allowlist is empty, or dedupe kicks in. Safe to call
    from any context (sync Celery task, async router, cron). Returns True
    when a send was attempted successfully, otherwise False.
    """
    payload = dict(payload or {})
    try:
        if not _should_send(event_type):
            return False

        renderer = EVENT_RENDERERS.get(event_type)
        if renderer is None:
            logger.warning("telegram_notify_unknown_event", event_type=event_type)
            return False

        try:
            rendered = renderer(payload)
        except UnknownEvent:
            return False
        except Exception as exc:  # noqa: BLE001 — never crash the caller
            logger.warning(
                "telegram_notify_render_failed",
                event_type=event_type,
                error=str(exc),
            )
            return False

        dedupe_key = rendered.get("dedupe_key") or event_type
        if not _dedupe_allow(event_type, str(dedupe_key)):
            logger.debug("telegram_notify_deduped", event_type=event_type, key=dedupe_key)
            return False

        chat_id = _primary_chat_id()
        if chat_id is None:
            logger.debug("telegram_notify_no_user")
            return False

        if rendered.get("document_path"):
            return _send_document(
                chat_id,
                rendered["text"],
                rendered["document_path"],
                filename=rendered.get("document_filename"),
                mime_type=rendered.get("document_mime_type"),
                reply_markup=rendered.get("reply_markup"),
                parse_mode=rendered.get("parse_mode", "Markdown"),
            )

        return _send(
            chat_id,
            rendered["text"],
            reply_markup=rendered.get("reply_markup"),
            parse_mode=rendered.get("parse_mode", "Markdown"),
        )
    except Exception as exc:  # noqa: BLE001 — absolute safety net
        logger.warning("telegram_notify_failed", event_type=event_type, error=str(exc))
        return False
