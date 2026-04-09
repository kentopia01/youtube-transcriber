# Fix Sprint Plan — 2026-03-21

## Goal
Apply 6 critical/high-priority fixes: API auth, chat memory bound, Haiku models, cost controls, 429 retry, audio cleanup, video time limit.

## Assumptions
- Python/FastAPI + Celery project (no npm/Node)
- Native venv at `.venv-native/`, Docker services running
- Pydantic-settings reads env vars from field names (uppercase), `Field(env=...)` is deprecated in v2
- Cost tracker uses sync SQLAlchemy (same pattern as Celery tasks)
- `tenacity` added to pyproject.toml and installed in both environments

## Steps

### FIX 1: API Auth Middleware
1. Add `api_key: str = ""` to `app/config.py`
2. Add HTTP middleware to `app/main.py`: reads X-API-Key header or api_key query param, skips /, /health, /static/*, logs warning if key empty
3. Add `API_KEY=` to `.env.example`

### FIX 2: Chat Session Memory Leak
- `app/routers/chat.py` send_message: remove selectinload, add bounded select(ChatMessage).limit(N)
- `app/telegram_bot.py` handle_message: same pattern, remove reload query

### FIX 3: Anthropic 429 Retry
- Add `tenacity>=8.2.0` to `pyproject.toml`
- Add `_call_anthropic_with_retry()` to chat.py, summarization.py, transcript_cleanup.py

### FIX 4a: Haiku/Sonnet Model Settings
- Add `anthropic_cleanup_model`, `anthropic_chat_model`, `anthropic_summary_model` to config
- Update services: cleanup→haiku, chat→haiku, summary→sonnet

### FIX 4b: Per-Video Duration Limit
- Add `max_video_duration_minutes: int = 120` to config
- In `app/tasks/download.py`: check duration after metadata fetch, fail with descriptive message

### FIX 4c: Daily LLM Budget Cap
- Add `daily_llm_budget_usd: float = 5.0` to config
- Create `app/services/cost_tracker.py` with record_usage, check_budget, get_today_cost, get_period_cost
- Create `app/models/llm_usage.py` ORM model
- Create `alembic/versions/007_add_llm_usage_table.py`
- Create `app/routers/llm_usage.py`: GET /api/llm/usage
- Wire check_budget before LLM calls (chat+cleanup, not summarization); record_usage after every call

### FIX 5: Celery Worker Plist
- Verified ~/Library/LaunchAgents/com.sentryclaw.yt-worker.plist — already has KeepAlive (SuccessfulExit=false), StandardOutPath, StandardErrorPath. No changes needed.

### FIX 6: Audio File Cleanup
- In `app/tasks/transcribe.py`: after successful transcription, delete audio file via os.unlink()

## Deviations
- Used simple Python defaults instead of Field(env=...) to avoid pydantic v2 deprecation warnings
- Docker container needed pip install tenacity after source volume reload
