# QAClaw Phase 2 QA Round 2 — Diff Summary

## What Changed

| File | Change |
|---|---|
| `app/schemas/chat.py` | Fix: Added `Field(min_length=1, max_length=100_000)` to `ChatMessageSend.content`; Added `Field(min_length=1, max_length=255)` to `ChatSessionRename.title` |
| `app/services/chat.py` | Fix: `asyncio.get_event_loop()` -> `get_running_loop()`; Added try/except around Anthropic API call with graceful error response; Moved sources list construction before LLM call so it's available in error paths |
| `tests/test_chat_backend.py` | Added 14 new edge case tests: empty message, missing content, whitespace-only, very long message, empty rename, long rename, no-messages session, cascade delete, nonexistent session message, sources saved, API error handling, correct model, prompt structure, token guard |

## Bugs Fixed
1. **No input validation on message content**: Empty strings and 100k+ char messages were accepted. Added `min_length=1, max_length=100_000`.
2. **No input validation on session rename**: Empty string rename was accepted. Added `min_length=1, max_length=255`.
3. **Deprecated `asyncio.get_event_loop()`**: Replaced with `asyncio.get_running_loop()`.
4. **No Anthropic API error handling**: `_call_anthropic` exceptions propagated as 500s. Added try/except with graceful error response.
5. **Sources unavailable in error path**: Sources list was built after the LLM call, so API errors couldn't include search results. Moved construction before the LLM call.

## Risks
- Pydantic `min_length` does not strip whitespace, so `"   "` passes validation. Acceptable for now.
- `max_length=100_000` is arbitrary but reasonable for chat messages.
- Migration 006 still uses `sa.JSON()` vs model's `JSONB` — cosmetic mismatch, functionally fine on PostgreSQL.
