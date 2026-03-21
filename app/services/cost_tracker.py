"""Simple daily LLM cost tracker using PostgreSQL."""

import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)

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


def record_usage(model: str, input_tokens: int, output_tokens: int) -> None:
    """Record LLM token usage to the database. Best-effort: logs errors but does not raise."""
    try:
        cost = estimate_cost(model, input_tokens, output_tokens)
        with Session(_get_engine()) as db:
            db.execute(
                text(
                    "INSERT INTO llm_usage (model, input_tokens, output_tokens, estimated_cost_usd) "
                    "VALUES (:model, :input_tokens, :output_tokens, :cost)"
                ),
                {"model": model, "input_tokens": input_tokens, "output_tokens": output_tokens, "cost": cost},
            )
            db.commit()
    except Exception as exc:
        logger.warning("cost_tracker_record_failed: %s", exc)


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
                    "SELECT COALESCE(SUM(estimated_cost_usd), 0) "
                    "FROM llm_usage "
                    "WHERE created_at >= NOW() - INTERVAL ':days days'"
                ),
                {"days": days},
            )
            return float(result.scalar() or 0)
    except Exception:
        # Fallback: use parameterized interval via Python string (safe — days is an int)
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

    today_cost = get_today_cost()
    if today_cost >= settings.daily_llm_budget_usd:
        raise BudgetExceededError(
            f"Daily LLM budget of ${settings.daily_llm_budget_usd:.2f} exceeded "
            f"(today's spend: ${today_cost:.4f})"
        )
