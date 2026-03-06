# BuildClaw Phase 2: Chat Backend

## Goal
Implement Phase 2 (Chat Backend) from CHAT_FEATURE_PLAN.md: database tables, ORM models, RAG chat service, and REST API endpoints for chat sessions and messages.

## Assumptions
- Phase 1 (toggle system) is complete and working (commit 0e07c0c)
- Anthropic SDK already installed
- Using sync Anthropic client via run_in_executor for async compatibility
- search.py already has chat_enabled_only support from Phase 1

## Steps
1. Read existing codebase: models, routers, search service, config, tests
2. Create Alembic migration 006: chat_sessions + chat_messages tables
3. Create DB models: ChatSession (app/models/chat_session.py), ChatMessage (app/models/chat_message.py)
4. Register models in app/models/__init__.py
5. Add chat config settings to app/config.py (chat_model, chat_max_history, chat_retrieval_top_k)
6. Create Pydantic schemas (app/schemas/chat.py)
7. Create chat service (app/services/chat.py) with RAG pipeline:
   - encode_query -> hybrid search (chat_enabled_only=True) -> build prompt -> call Anthropic
   - Token limit safeguard: truncate history if estimated tokens > 150k
   - Uses run_in_executor for sync Anthropic client
8. Create chat router (app/routers/chat.py) with 6 endpoints:
   - POST /api/chat/sessions — create session
   - GET /api/chat/sessions — list sessions (paginated)
   - GET /api/chat/sessions/{id} — get session with messages
   - DELETE /api/chat/sessions/{id} — delete session + cascade messages
   - PATCH /api/chat/sessions/{id} — rename session
   - POST /api/chat/sessions/{id}/messages — send message, get RAG response
   - Auto-title from first message (first 50 chars + "...")
9. Register chat router in app/main.py
10. Write 26 tests in tests/test_chat_backend.py
11. Run full test suite: 505 passed
12. Create handoff docs, commit, push
