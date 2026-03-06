# Phase 1: Toggle System — Implementation Plan

## Goal
Add chat_enabled toggle to videos and channels, with API endpoints, search filter support, and library UI toggles. This is Phase 1 of the "Chat with Transcripts" feature plan.

## Assumptions
- Existing Alembic migration chain ends at 004
- HTMX is already loaded in base.html
- Toggle defaults to true (all existing videos/channels are chat-enabled)
- Existing search page behavior unchanged (chat_enabled_only defaults to False)

## Steps
1. Add `chat_enabled BOOLEAN NOT NULL DEFAULT true` to Video and Channel SQLAlchemy models
2. Create Alembic migration 005 with `server_default=sa.text("true")`
3. Add `ChatToggle` Pydantic schema (`enabled: bool`)
4. Add `PATCH /api/videos/{video_id}/chat-toggle` endpoint
5. Add `PATCH /api/channels/{channel_id}/chat-toggle` endpoint (bulk-updates all channel videos)
6. Update `_build_where_clause()` to accept `chat_enabled_only` param, adding `v.chat_enabled = true` filter
7. Thread `chat_enabled_only` through `_vector_search`, `_keyword_search`, `_hybrid_search`, and `semantic_search`
8. Add toggle switch UI to video cards and channel cards in library.html
9. Add CSS for toggle pill switch with dimming (opacity 0.6) for disabled items
10. Write tests: video toggle on/off, channel bulk toggle, 404 cases, search filter pass-through
11. Run full test suite — verify all pass
