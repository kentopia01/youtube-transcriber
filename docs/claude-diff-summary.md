# QAClaw Phase 2 QA Rounds 8-10 — Diff Summary

## What Changed

| File | Change |
|---|---|
| `tests/test_chat.py` | Added 5 tests in Round 8 + 9 tests in Round 9 + 4 tests in Round 10 |
| `docs/claude-diff-summary.md` | Updated to reflect QA Rounds 8-10 |
| `docs/claude-test-results.txt` | Updated with full suite results |

## Tests Added (Round 8 — code-review-driven gaps)
1. `test_empty_string_title_blocks_auto_title` — documents `title=""` does NOT trigger auto-title
2. `test_odd_number_history_messages` — non-paired history (3 msgs) works correctly
3. `test_newlines_in_message_content_preserved` — newlines in content preserved through pipeline
4. `test_search_query_text_passed_correctly` — question passed as both embedding and text query
5. `test_max_tokens_4096_in_anthropic_call` — verifies model arg passed to _call_anthropic

## Tests Added (Round 9 — final gap tests)
1. `test_get_anthropic_client_singleton` — verifies client is cached (only one instantiation)
2. `test_rename_single_char_boundary` — rename to exactly 1 char succeeds (min_length boundary)
3. `test_token_guard_only_question_survives` — single 800k history message fully dropped, only question remains
4. `test_create_session_extra_fields_ignored` — unknown fields in body don't cause errors
5. `test_model_from_settings_not_hardcoded` — model passed to Anthropic comes from settings.chat_model
6. `test_build_messages_context_prefix_present` — verifies "Context from video transcripts:" and "Question:" format
7. `test_send_message_db_commit_called` — both user+assistant messages added and committed
8. `test_system_prompt_passed_as_system_not_message` — system prompt is separate from messages list
9. `test_send_message_returns_correct_session_id` — assistant message has correct session_id

## Tests Added (Round 10 — isolation & ORM checks)
1. `test_session_isolation_different_sessions` — messages from session A do not appear in session B's history
2. `test_models_importable_from_package` — ChatSession and ChatMessage importable from app.models
3. `test_chat_message_fk_references_chat_sessions` — FK on session_id correctly targets chat_sessions.id
4. `test_chat_session_cascade_delete_orphan` — relationship cascade includes delete-orphan

## Bugs Fixed
None — no bugs found across 10 rounds of QA. Implementation is solid.

## Code Review Summary (Full)
All Phase 2 components verified against CHAT_FEATURE_PLAN.md:
- **Models**: proper SQLAlchemy mapped columns, JSONB sources, relationship cascade, onupdate for updated_at
- **Schemas**: Pydantic validation with min/max length, from_attributes, ChatSourceOut structure
- **Service**: RAG pipeline with chat_enabled_only=True, history trimming to chat_max_history*2, 150k token guard, graceful error handling for missing API key and API errors, sync Anthropic call in executor, singleton client
- **Router**: complete CRUD (create/list/get/delete/rename), auto-title on first message, history built from loaded messages, updated_at touch
- **Config**: all 3 chat settings present with correct defaults (model=claude-sonnet-4-20250514, max_history=10, top_k=10)
- **Search integration**: chat_enabled_only properly propagated through vector/keyword/hybrid modes
- **Anthropic API call**: correct model from settings, system prompt with video transcript grounding, max_tokens=4096

## Test Coverage Summary
- **113 tests** in `test_chat.py` covering Phase 2 chat backend (10 rounds)
- **563 tests total** across the full suite, all passing

## Risks
- `title=""` is treated differently from `title=None` — empty string blocks auto-title. Acceptable but worth noting for Phase 3 UI.
- Pydantic `min_length` does not strip whitespace — `"   "` passes validation. Acceptable for now.
- Token estimation (4 chars/token) is rough but sufficient as a safety guard.
- Migration 006 exists at `alembic/versions/006_create_chat_tables.py`.
