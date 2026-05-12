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

SIDE_EFFECT_BEST_EFFORT = "best_effort_side_effect"
SIDE_EFFECT_EXPECTED_EXTERNAL = "expected_external_failure"
SIDE_EFFECT_BUG_MASK = "bug_mask_candidate"


def _exception_fields(exc: Exception, *, limit: int = 500) -> dict[str, str]:
    return {
        "exception_type": exc.__class__.__name__,
        "error_message": str(exc)[:limit],
    }

_SAFE_ENTITY_KEYS = ("video_id", "job_id", "channel_id", "batch_id", "report_path")


def _safe_entity_context(payload: dict[str, Any] | None) -> dict[str, str]:
    context: dict[str, str] = {}
    for key in _SAFE_ENTITY_KEYS:
        value = (payload or {}).get(key)
        if value is not None:
            context[key] = str(value)[:300]
    return context


# In-process dedupe: (event_type, dedupe_key) -> last-successful-send unix ts.
# Failed sends must not poison dedupe, so in-flight events are reserved
# separately and only committed after Telegram accepts the send.
_DEDUPE: dict[tuple[str, str], float] = {}
_DEDUPE_PENDING: set[tuple[str, str]] = set()
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
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning(
            "telegram_notify_state_load_failed",
            boundary="telegram_notify.state_load",
            category=SIDE_EFFECT_BEST_EFFORT,
            state_path=str(p),
            outcome="settings_fallback_used",
            **_exception_fields(exc),
        )
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


def _dedupe_cleanup_locked(now: float) -> None:
    if len(_DEDUPE) <= 500:
        return
    cutoff = now - _DEDUPE_WINDOW_SECONDS * 2
    for k, ts in list(_DEDUPE.items()):
        if ts < cutoff:
            _DEDUPE.pop(k, None)


def _dedupe_reserve(event_type: str, dedupe_key: str) -> bool:
    """Reserve an event if it is not recently sent or already in-flight."""
    now = time.time()
    key = (event_type, dedupe_key)
    with _DEDUPE_LOCK:
        last = _DEDUPE.get(key)
        if last is not None and now - last < _DEDUPE_WINDOW_SECONDS:
            return False
        if key in _DEDUPE_PENDING:
            return False
        _DEDUPE_PENDING.add(key)
        _dedupe_cleanup_locked(now)
    return True


def _dedupe_finish(event_type: str, dedupe_key: str, *, sent: bool) -> None:
    """Release an in-flight dedupe reservation, committing only successes."""
    now = time.time()
    key = (event_type, dedupe_key)
    with _DEDUPE_LOCK:
        _DEDUPE_PENDING.discard(key)
        if sent:
            _DEDUPE[key] = now
            _dedupe_cleanup_locked(now)


def _send(
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
    parse_mode: str | None = "Markdown",
    *,
    event_type: str | None = None,
    dedupe_key: str | None = None,
    entity_context: dict[str, str] | None = None,
) -> bool:
    """POST sendMessage. Short timeout, all failures swallowed."""
    import requests  # local import so tests can import this module without the dep

    token = settings.telegram_bot_token
    if not token:
        logger.debug(
            "telegram_notify_no_token",
            boundary="telegram_notify.send_message",
            category=SIDE_EFFECT_BEST_EFFORT,
            event_type=event_type,
            dedupe_key=dedupe_key,
            outcome="suppressed",
            **(entity_context or {}),
        )
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
                boundary="telegram_notify.send_message",
                category=SIDE_EFFECT_EXPECTED_EXTERNAL,
                event_type=event_type,
                dedupe_key=dedupe_key,
                status_code=getattr(resp, "status_code", None),
                response_text=getattr(resp, "text", "")[:200],
                exception_type=None,
                error_message=getattr(resp, "text", "")[:200],
                outcome="suppressed",
                **(entity_context or {}),
            )
            return False
        return True
    except Exception as exc:  # noqa: BLE001 — fire-and-forget
        logger.warning(
            "telegram_notify_send_failed",
            boundary="telegram_notify.send_message",
            category=SIDE_EFFECT_EXPECTED_EXTERNAL,
            event_type=event_type,
            dedupe_key=dedupe_key,
            outcome="suppressed",
            **(entity_context or {}),
            **_exception_fields(exc),
        )
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
    event_type: str | None = None,
    dedupe_key: str | None = None,
    entity_context: dict[str, str] | None = None,
) -> bool:
    """POST sendDocument with a local file attachment."""
    import requests  # local import so tests can import this module without the dep

    token = settings.telegram_bot_token
    if not token:
        logger.debug(
            "telegram_notify_no_token",
            boundary="telegram_notify.send_document",
            category=SIDE_EFFECT_BEST_EFFORT,
            event_type=event_type,
            dedupe_key=dedupe_key,
            document_path=document_path,
            outcome="suppressed",
            **(entity_context or {}),
        )
        return False

    path = Path(document_path)
    if not path.exists() or not path.is_file():
        logger.warning(
            "telegram_notify_document_missing",
            boundary="telegram_notify.send_document",
            category=SIDE_EFFECT_EXPECTED_EXTERNAL,
            event_type=event_type,
            dedupe_key=dedupe_key,
            document_path=str(path),
            exception_type=None,
            error_message="document_missing",
            outcome="suppressed",
            **(entity_context or {}),
        )
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
                boundary="telegram_notify.send_document",
                category=SIDE_EFFECT_EXPECTED_EXTERNAL,
                event_type=event_type,
                dedupe_key=dedupe_key,
                document_path=str(path),
                status_code=getattr(resp, "status_code", None),
                response_text=getattr(resp, "text", "")[:200],
                exception_type=None,
                error_message=getattr(resp, "text", "")[:200],
                outcome="suppressed",
                **(entity_context or {}),
            )
            return False
        return True
    except Exception as exc:  # noqa: BLE001 — fire-and-forget
        logger.warning(
            "telegram_notify_document_send_failed",
            boundary="telegram_notify.send_document",
            category=SIDE_EFFECT_EXPECTED_EXTERNAL,
            event_type=event_type,
            dedupe_key=dedupe_key,
            document_path=str(path),
            outcome="suppressed",
            **(entity_context or {}),
            **_exception_fields(exc),
        )
        return False


def notify(event_type: str, payload: dict | None = None) -> bool:
    """Fire-and-forget push notification.

    Never raises. Silent no-op when the event is muted, the bot isn't
    configured, the allowlist is empty, or dedupe kicks in. Safe to call
    from any context (sync Celery task, async router, cron). Returns True
    when a send was attempted successfully, otherwise False.
    """
    entity_context: dict[str, str] = {}
    try:
        payload = dict(payload or {})
        entity_context = _safe_entity_context(payload)
        if not _should_send(event_type):
            return False

        renderer = EVENT_RENDERERS.get(event_type)
        if renderer is None:
            logger.warning(
                "telegram_notify_unknown_event",
                boundary="telegram_notify.render",
                category=SIDE_EFFECT_BUG_MASK,
                event_type=event_type,
                exception_type=None,
                error_message="unknown_event",
                outcome="suppressed",
                **entity_context,
            )
            return False

        try:
            rendered = renderer(payload)
        except UnknownEvent:
            return False
        except Exception as exc:  # noqa: BLE001 — never crash the caller
            logger.warning(
                "telegram_notify_render_failed",
                boundary="telegram_notify.render",
                category=SIDE_EFFECT_BUG_MASK,
                event_type=event_type,
                outcome="suppressed",
                **entity_context,
                **_exception_fields(exc),
            )
            return False

        dedupe_key = str(rendered.get("dedupe_key") or event_type)
        if not _dedupe_reserve(event_type, dedupe_key):
            logger.debug(
                "telegram_notify_deduped",
                boundary="telegram_notify.dedupe",
                category=SIDE_EFFECT_BEST_EFFORT,
                event_type=event_type,
                dedupe_key=dedupe_key,
                outcome="suppressed",
                **entity_context,
            )
            return False

        sent = False
        try:
            chat_id = _primary_chat_id()
            if chat_id is None:
                logger.debug(
                    "telegram_notify_no_user",
                    boundary="telegram_notify.resolve_recipient",
                    category=SIDE_EFFECT_BEST_EFFORT,
                    event_type=event_type,
                    dedupe_key=dedupe_key,
                    outcome="suppressed",
                    **entity_context,
                )
                return False

            if rendered.get("document_path"):
                sent = _send_document(
                    chat_id,
                    rendered["text"],
                    rendered["document_path"],
                    filename=rendered.get("document_filename"),
                    mime_type=rendered.get("document_mime_type"),
                    reply_markup=rendered.get("reply_markup"),
                    parse_mode=rendered.get("parse_mode", "Markdown"),
                    event_type=event_type,
                    dedupe_key=dedupe_key,
                    entity_context=entity_context,
                )
                return sent

            sent = _send(
                chat_id,
                rendered["text"],
                reply_markup=rendered.get("reply_markup"),
                parse_mode=rendered.get("parse_mode", "Markdown"),
                event_type=event_type,
                dedupe_key=dedupe_key,
                entity_context=entity_context,
            )
            return sent
        finally:
            try:
                _dedupe_finish(event_type, dedupe_key, sent=sent)
            except Exception as exc:  # noqa: BLE001 — dedupe accounting must not affect callers
                logger.warning(
                    "telegram_notify_dedupe_finish_failed",
                    boundary="telegram_notify.dedupe",
                    category=SIDE_EFFECT_BEST_EFFORT,
                    event_type=event_type,
                    dedupe_key=dedupe_key,
                    outcome="caller_continued",
                    **entity_context,
                    **_exception_fields(exc),
                )
    except Exception as exc:  # noqa: BLE001 — absolute safety net
        logger.warning(
            "telegram_notify_failed",
            boundary="telegram_notify.notify",
            category=SIDE_EFFECT_BUG_MASK,
            event_type=event_type,
            outcome="suppressed",
            **entity_context,
            **_exception_fields(exc),
        )
        return False
