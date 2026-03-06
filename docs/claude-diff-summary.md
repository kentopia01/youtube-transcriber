# QAClaw Phase 2 QA Round 5 — Diff Summary

## What Changed

| File | Change |
|---|---|
| `tests/test_chat.py` | Added 8 new edge case tests in `TestQAClawRound5` class |
| `docs/claude-diff-summary.md` | Updated to reflect QA Round 5 |
| `docs/claude-test-results.txt` | Full test output (527 passed) |

## Tests Added (Round 5)
1. `test_concurrent_messages_both_succeed` — sequential messages to same session both succeed, title not overwritten
2. `test_system_prompt_mentions_video_transcripts` — system prompt grounds assistant in transcript content
3. `test_system_prompt_instructs_citation` — system prompt instructs source citation
4. `test_call_anthropic_passes_correct_params` — unit test for `_call_anthropic` verifying model/system/messages/max_tokens
5. `test_token_guard_preserves_current_question` — massive history still preserves current question after token guard
6. `test_send_message_content_type_json_required` — non-JSON body returns 422
7. `test_create_session_invalid_json_returns_422` — malformed JSON returns 422
8. `test_assistant_message_has_model_and_tokens` — assistant message object stores model name and token counts

## Bugs Fixed
None — no bugs found across 5 rounds of QA. Implementation is solid.

## Code Review Summary (Full)
All Phase 2 components verified against CHAT_FEATURE_PLAN.md:
- Migration 006: correct table structure, FK cascade, index on session_id
- Models: proper SQLAlchemy mapped columns, JSONB sources, relationship cascade, onupdate for updated_at
- Schemas: Pydantic validation with min/max length, from_attributes, ChatSourceOut structure
- Service: RAG pipeline with chat_enabled_only=True, history trimming to chat_max_history*2, 150k token guard, graceful error handling for missing API key and API errors
- Router: complete CRUD (create/list/get/delete/rename), auto-title on first message, history built from loaded messages, updated_at touch
- Config: all 3 chat settings present with correct defaults (model=claude-sonnet-4-20250514, max_history=10, top_k=10)
- Search integration: chat_enabled_only properly propagated through vector/keyword/hybrid modes

## Test Coverage Summary
- **77 tests** in `test_chat.py` covering Phase 2 chat backend
- **527 tests total** across the full suite, all passing

## Risks
- Pydantic `min_length` does not strip whitespace — `"   "` passes validation. Acceptable for now.
- Token estimation (4 chars/token) is rough but sufficient as a safety guard.
- Session.messages loaded via selectinload — new user_msg added via FK (not relationship) won't appear in collection, so no duplicate question in history. Safe.
