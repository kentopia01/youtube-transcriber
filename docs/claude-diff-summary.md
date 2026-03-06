# BuildClaw Phase 2: Chat Backend — Diff Summary

## What Changed

| File | Change |
|---|---|
| `alembic/versions/006_create_chat_tables.py` | New migration: chat_sessions + chat_messages tables with CASCADE FK, index on session_id |
| `app/models/chat_session.py` | New model: ChatSession (UUID PK, title nullable, platform, telegram_chat_id, timestamps) |
| `app/models/chat_message.py` | New model: ChatMessage (UUID PK, session FK, role, content, sources JSONB, model, token counts) |
| `app/models/__init__.py` | Registered ChatSession and ChatMessage |
| `app/config.py` | Added chat_model, chat_max_history, chat_retrieval_top_k settings |
| `app/schemas/chat.py` | New Pydantic schemas: ChatSessionCreate, ChatSessionRename, ChatMessageSend, ChatSourceOut, ChatMessageOut, ChatSessionOut, ChatSessionDetail |
| `app/services/chat.py` | New RAG chat service: encode query, hybrid search (chat_enabled_only=True), build prompt with context + history, call Anthropic via run_in_executor, token limit safeguard |
| `app/routers/chat.py` | New router: 6 endpoints for session CRUD + send message with RAG response + auto-title |
| `app/main.py` | Registered chat router |
| `tests/test_chat_backend.py` | 26 tests: session CRUD, message send, sources, auto-title, service helpers, RAG integration |

## Why
Phase 2 of the Chat with Transcripts feature. Adds the full backend: database tables, RAG retrieval pipeline, Anthropic LLM integration, and REST API for chat sessions and messages.

## Risks
- Anthropic API calls use sync client in run_in_executor — works but adds slight overhead vs native async client
- Session title auto-generation is simple (first 50 chars) — could be enhanced with LLM-generated titles later
- No rate limiting on chat API endpoints yet
- Token costs from Sonnet calls — configurable via chat_model setting
- Token estimation for 150k limit is rough (chars / 4) — sufficient as a safety net

## Plan Deviations
- None — implementation follows the plan exactly
