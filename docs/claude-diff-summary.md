# QAClaw Phase 2: Chat Backend QA — Diff Summary

## What Changed

| File | Change |
|---|---|
| `alembic/versions/006_create_chat_tables.py` | Fix: `sa.JSON()` -> `JSONB()` to match model's `JSONB` column type |
| `app/services/chat.py` | Fix: missing API key now returns actual `sources` (from search) instead of empty list |
| `tests/test_chat.py` | Added 10 new edge-case tests: special chars, long messages, pagination validation, sources JSONB, 150k token guard, search failure, API key missing, multi-turn history, delete empty session |
| `tests/test_chat_backend.py` | Removed — duplicate of test_chat.py (~70% overlap). Unique tests merged into test_chat.py |

## Why
QA review of Phase 2 chat backend. Found 2 bugs and test coverage gaps.

## Bugs Fixed
1. **Migration JSONB mismatch**: Migration 006 used `sa.JSON()` but model uses `JSONB`. PostgreSQL would create a JSON column instead of JSONB, losing GIN index support and `@>` operator.
2. **Empty sources on missing API key**: `chat_with_context` returned `sources: []` when API key was missing, even though search had succeeded and computed valid sources. The LLM error path correctly returned sources, but the API key path didn't.

## Risks
- `asyncio.get_running_loop()` was already fixed by BuildClaw (confirmed in final code)
- No migration for existing databases with `JSON` column — if 006 was already applied, manual `ALTER COLUMN sources TYPE JSONB` needed

## Test Results
- 490 tests passed, 0 failed (40 chat-specific tests)
