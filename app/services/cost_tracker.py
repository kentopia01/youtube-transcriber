"""Simple daily LLM cost tracker using PostgreSQL."""

import contextvars
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)

# Ambient source tag for LLM calls made within a Celery task or async context.
# Set at task entry; read by record_usage. Lets us segment auto-ingest spend
# without threading `source` through every service signature.
_cost_source_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_cost_source", default=None
)


def set_cost_source(source: str | None) -> None:
    """Set the ambient ``source`` tag for subsequent ``record_usage`` calls."""
    _cost_source_ctx.set(source)


def source_for_attempt_reason(reason: str | None) -> str | None:
    """Map a job's ``attempt_creation_reason`` to a cost-tracker source tag."""
    if reason and reason.startswith("auto_ingest"):
        return "auto_ingest"
    return None

# Cost per million tokens (input, output) by model prefix
_RATES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (0.80, 4.00),
    "claude-haiku-4-20250514": (0.80, 4.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
}

_sync_engine = None


def _get_engine():
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(settings.database_url_sync)
    return _sync_engine


class BudgetExceededError(Exception):
    pass


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for an Anthropic API call."""
    rate_in, rate_out = _RATES.get(model, (3.00, 15.00))
    return (input_tokens * rate_in + output_tokens * rate_out) / 1_000_000


def record_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    source: str | None = None,
) -> None:
    """Record LLM token usage to the database. Best-effort: logs errors but does not raise.

    ``source`` tags the triggering context (e.g. ``"auto_ingest"``). Used by the
    separated autonomous-work budget cap. Pass ``None`` for user-triggered work.
    """
    try:
        cost = estimate_cost(model, input_tokens, output_tokens)
        effective_source = source if source is not None else _cost_source_ctx.get()
        with Session(_get_engine()) as db:
            db.execute(
                text(
                    "INSERT INTO llm_usage (model, input_tokens, output_tokens, estimated_cost_usd, source) "
                    "VALUES (:model, :input_tokens, :output_tokens, :cost, :source)"
                ),
                {
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost": cost,
                    "source": effective_source,
                },
            )
            db.commit()
    except Exception as exc:
        logger.warning("cost_tracker_record_failed: %s", exc)


def get_today_cost_by_source(source: str) -> float:
    """Today's spend (UTC) filtered to a specific ``source`` tag."""
    try:
        with Session(_get_engine()) as db:
            result = db.execute(
                text(
                    "SELECT COALESCE(SUM(estimated_cost_usd), 0) "
                    "FROM llm_usage "
                    "WHERE created_at >= CURRENT_DATE AT TIME ZONE 'UTC' "
                    "AND source = :source"
                ),
                {"source": source},
            )
            return float(result.scalar() or 0)
    except Exception as exc:
        logger.warning("cost_tracker_get_today_source_failed: %s", exc)
        return 0.0


def auto_ingest_budget_remaining() -> float:
    """USD remaining before the autonomous-work daily cap kicks in."""
    cap = getattr(settings, "auto_ingest_daily_cost_cap_usd", 4.0)
    spent = get_today_cost_by_source("auto_ingest")
    return max(0.0, cap - spent)


def get_today_cost() -> float:
    """Return total estimated cost for today (UTC) in USD."""
    try:
        with Session(_get_engine()) as db:
            result = db.execute(
                text(
                    "SELECT COALESCE(SUM(estimated_cost_usd), 0) "
                    "FROM llm_usage "
                    "WHERE created_at >= CURRENT_DATE AT TIME ZONE 'UTC'"
                )
            )
            return float(result.scalar() or 0)
    except Exception as exc:
        logger.warning("cost_tracker_get_today_failed: %s", exc)
        return 0.0


def get_period_cost(days: int = 7) -> float:
    """Return total estimated cost for the past N days in USD."""
    try:
        with Session(_get_engine()) as db:
            result = db.execute(
                text(
                    f"SELECT COALESCE(SUM(estimated_cost_usd), 0) "
                    f"FROM llm_usage "
                    f"WHERE created_at >= NOW() - INTERVAL '{int(days)} days'"
                )
            )
            return float(result.scalar() or 0)
    except Exception as exc:
        logger.warning("cost_tracker_get_period_failed: %s", exc)
        return 0.0


def check_budget() -> None:
    """Raise BudgetExceededError if today's spend >= daily budget. Safe to call from sync context."""
    if settings.daily_llm_budget_usd <= 0:
        return  # Budget enforcement disabled

    cap = settings.daily_llm_budget_usd
    today_cost = get_today_cost()

    try:
        from app.services.telegram_notify import notify as _tg_notify

        if today_cost >= cap:
            _tg_notify("cost.threshold_100", {"spent": today_cost, "cap": cap})
        elif today_cost >= cap * 0.8:
            _tg_notify("cost.threshold_80", {"spent": today_cost, "cap": cap})
    except Exception:  # noqa: BLE001
        pass

    if today_cost >= cap:
        raise BudgetExceededError(
            f"Daily LLM budget of ${cap:.2f} exceeded (today's spend: ${today_cost:.4f})"
        )
