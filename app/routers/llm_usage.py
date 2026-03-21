"""LLM usage and cost reporting endpoints."""

from fastapi import APIRouter

from app.services import cost_tracker

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.get("/usage")
async def get_llm_usage():
    """Return today's and 7-day total estimated LLM spend in USD."""
    today = cost_tracker.get_today_cost()
    seven_day = cost_tracker.get_period_cost(days=7)
    return {
        "today_usd": round(today, 6),
        "seven_day_usd": round(seven_day, 6),
    }
