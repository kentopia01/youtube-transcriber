# QAClaw Phase 2 QA Round 12 — Diff Summary

## What Changed

| File | Change |
|---|---|
| `tests/test_chat.py` | Added 7 new tests in `TestQAClawRound12` class |
| `docs/claude-plan.md` | Updated to reflect QA Round 12 |
| `docs/claude-diff-summary.md` | Updated to reflect QA Round 12 |
| `docs/claude-test-results.txt` | Updated with 583-test results |

## Tests Added (Round 12)
1. `test_rate_limit_error_handled_gracefully` — Anthropic RateLimitError (429) returns user-friendly error, not crash
2. `test_history_order_preserved_in_llm_call` — 4 history messages + current question appear in correct chronological order
3. `test_sources_with_none_timestamps_valid` — chunks with None start_time/end_time produce valid sources dict
4. `test_token_guard_huge_question_no_history` — 800k-char question with no history still calls LLM (while loop terminates at len==1)
5. `test_history_excludes_current_user_message` — new user message added via session_id doesn't leak into eagerly-loaded history
6. `test_no_context_prompt_still_well_formed` — empty search results still produce "Context from video transcripts:" prefix
7. `test_assistant_message_role_is_always_assistant` — saved assistant message has role='assistant' in both response and DB

## Bugs Fixed
None — no bugs found across 12 rounds of QA. Implementation is solid.

## Code Review Summary (Full)
All Phase 2 components verified against CHAT_FEATURE_PLAN.md:
- **Migration 006**: chat_sessions + chat_messages tables, FK with CASCADE, session_id index, correct downgrade order
- **Models**: proper SQLAlchemy mapped columns, JSONB sources, relationship cascade with delete-orphan, onupdate for updated_at
- **Schemas**: Pydantic validation with min/max length, from_attributes config, ChatSourceOut with optional fields
- **Service**: RAG pipeline with chat_enabled_only=True, history trimming to chat_max_history*2, 150k token guard, graceful error handling for missing API key and API errors, sync Anthropic call in executor, singleton client with API key
- **Router**: complete CRUD (create/list/get/delete/rename), auto-title on first message, history built from loaded messages, updated_at touch, selectinload for eager loading
- **Config**: all 3 chat settings present with correct defaults (model=claude-sonnet-4-20250514, max_history=10, top_k=10)
- **Search integration**: chat_enabled_only properly propagated through vector/keyword/hybrid modes via _build_where_clause

## Test Coverage Summary
- **133 tests** in `test_chat.py` covering Phase 2 chat backend (12 rounds)
- **583 tests total** across the full suite, all passing

## Risks
- `title=""` is treated differently from `title=None` — empty string blocks auto-title. Acceptable but worth noting for Phase 3 UI.
- Pydantic `min_length` does not strip whitespace — `"   "` passes validation. Acceptable for now.
- Token estimation (4 chars/token) is rough but sufficient as a safety guard.
- Platform field has no enum validation — any string is accepted. Fine for now, but Phase 4 (Telegram) may want to restrict.
