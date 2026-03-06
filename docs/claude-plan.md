# BuildClaw Phase 2: Chat Backend (Sessions + RAG + API)

## Goal
Implement the full chat backend for the youtube-transcriber: session management, RAG pipeline, and API endpoints as specified in CHAT_FEATURE_PLAN.md Phase 2.

## Assumptions
- Phase 1 (toggle system) is complete — `chat_enabled` columns exist on videos/channels
- `semantic_search()` already supports `chat_enabled_only` parameter
- Anthropic SDK is installed; `encode_query` uses sentence_transformers for embeddings
- Model ID `claude-sonnet-4-20250514` matches existing format in config (confirmed against `cleanup_model` and `summary_model`)

## Steps
1. Create `app/models/chat_session.py` — UUID PK, title, platform, telegram_chat_id, timestamps
2. Create `app/models/chat_message.py` — UUID PK, FK to session, role, content, JSONB sources, token counts
3. Register both models in `app/models/__init__.py`
4. Create Alembic migration 006 — chat_sessions + chat_messages tables with index
5. Add config: `chat_model`, `chat_max_history`, `chat_retrieval_top_k` to `app/config.py`
6. Create `app/schemas/chat.py` — Pydantic models for all request/response types
7. Create `app/services/chat.py` — RAG pipeline: encode query -> hybrid search (chat_enabled_only) -> build prompt with history -> call Anthropic -> return answer + sources
8. Create `app/routers/chat.py` — 6 endpoints (create/list/get/delete/rename sessions + send message)
9. Register router in `app/main.py`
10. Auto-title: first 50 chars of first message with ellipsis
11. Error handling: graceful fallback for missing deps/API key
12. Create `tests/test_chat_backend.py` — 28 tests covering CRUD, messaging, RAG, error paths
13. Run full suite: 507 passed
