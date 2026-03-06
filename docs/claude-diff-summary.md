# BuildClaw Phase 2: Chat Backend — Diff Summary

## What Changed

| File | Change |
|---|---|
| `app/models/chat_session.py` | New — ChatSession model (UUID PK, title, platform, telegram_chat_id, timestamps, messages relationship) |
| `app/models/chat_message.py` | New — ChatMessage model (UUID PK, FK session_id, role, content, JSONB sources, model, token counts) |
| `app/models/__init__.py` | Added ChatSession + ChatMessage imports |
| `alembic/versions/006_create_chat_tables.py` | New — migration creating chat_sessions, chat_messages tables + session_id index |
| `app/config.py` | Added chat_model, chat_max_history, chat_retrieval_top_k settings |
| `app/schemas/chat.py` | New — Pydantic schemas (ChatSessionCreate, ChatSessionRename, ChatMessageSend, ChatSourceOut, ChatMessageOut, ChatSessionOut, ChatSessionDetail) |
| `app/services/chat.py` | New — RAG pipeline: encode_query -> hybrid search (chat_enabled_only=True) -> build prompt with history -> Anthropic call -> sources. Includes 150k token guard, graceful error handling |
| `app/routers/chat.py` | New — 6 API endpoints (POST/GET/DELETE/PATCH sessions, POST messages). Auto-title on first message |
| `app/main.py` | Registered chat router |
| `tests/test_chat_backend.py` | New — 28 tests: session CRUD (7), send message (7), service helpers (5), RAG integration (4), error handling (2), chat_enabled filter (1), validation (2) |

## Why
Phase 2 of CHAT_FEATURE_PLAN.md — enables conversational chat grounded in video transcript content via RAG.

## Risks
- `encode_query()` requires sentence_transformers — handled with try/except fallback
- Missing API key — returns clear error message instead of exception
- Token overflow — 150k token limit with history trimming

## Plan Deviations
- None — all items from Phase 2 spec implemented as planned
