# Fix Sprint Diff Summary — 2026-03-21

## What Changed

| File | Change |
|------|--------|
| `app/config.py` | Added: api_key, anthropic_cleanup_model, anthropic_chat_model, anthropic_summary_model, max_video_duration_minutes, daily_llm_budget_usd |
| `app/main.py` | Added API key middleware + llm_usage router |
| `app/routers/chat.py` | Replaced selectinload with bounded ChatMessage query (FIX 2) |
| `app/telegram_bot.py` | Replaced selectinload+reload with bounded ChatMessage query (FIX 2) |
| `app/services/chat.py` | Added tenacity retry, check_budget, record_usage, switched to anthropic_chat_model (haiku) |
| `app/services/summarization.py` | Added tenacity retry, record_usage, switched to anthropic_summary_model (sonnet) |
| `app/services/transcript_cleanup.py` | Added tenacity retry, check_budget, record_usage, switched to anthropic_cleanup_model (haiku) |
| `app/tasks/cleanup.py` | Uses settings.anthropic_cleanup_model |
| `app/tasks/download.py` | Added duration limit check after metadata fetch |
| `app/tasks/transcribe.py` | Added audio file deletion after successful transcription |
| `app/services/cost_tracker.py` | **NEW** — sync LLM usage tracker with record_usage, check_budget, get_today_cost, get_period_cost |
| `app/models/llm_usage.py` | **NEW** — SQLAlchemy ORM for llm_usage table |
| `alembic/versions/007_add_llm_usage_table.py` | **NEW** — migration adding llm_usage table + index |
| `app/routers/llm_usage.py` | **NEW** — GET /api/llm/usage endpoint |
| `pyproject.toml` | Added tenacity>=8.2.0 dependency |
| `.env.example` | Added API_KEY, MAX_VIDEO_DURATION_MINUTES, DAILY_LLM_BUDGET_USD |
| `tests/test_cost_tracker.py` | **NEW** — unit tests for cost tracker (estimate_cost, record_usage, check_budget) |
| `tests/test_chat.py` | Updated 4 tests to match new bounded history query pattern (provides 2nd execute result) |
| `tests/test_telegram_bot.py` | Updated 2 tests to match new bounded history query pattern |

## Why

- **API auth**: Network-accessible deployments need protection; dev mode (empty key) retains zero-config UX
- **Memory leak**: selectinload fetched ALL messages; sessions with long history would OOM workers
- **429 retry**: Anthropic rate-limits can cause transient failures; exponential backoff (4s→60s, 3 attempts) handles spikes
- **Haiku for chat/cleanup**: Significant cost reduction; Haiku is adequate for Q&A and filler word removal; Sonnet retained only for summaries
- **Duration limit**: Prevents accidental queueing of 4-hour conference talks that would consume 30+ min of GPU time
- **Cost cap**: Hard daily budget prevents runaway charges in production; per-call tracking enables observability
- **Audio cleanup**: Audio files are large (100MB+); cleaning them up after transcription frees significant disk space

## Risks

- **Cost tracker DB**: Uses sync SQLAlchemy with lazy engine init. If DB is unavailable, record_usage logs a warning but does not raise (best-effort). check_budget returns 0 cost on DB error (permissive failure).
- **Alembic migration**: `007_add_llm_usage_table.py` must be run before the cost tracker is called. Until then, record_usage will silently fail (logs warning).
- **tenacity in Docker**: Docker image must be rebuilt (or `pip install tenacity` run manually) to pick up new dependency.
- **Model strings**: New `anthropic_*_model` settings use short names (`claude-haiku-4-5`); Anthropic API accepts these.

## Unresolved

- llm_usage table migration needs to run: `alembic upgrade head`
- No test for duration limit in download task (would require mocking yt-dlp)
