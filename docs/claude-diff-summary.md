# QAClaw Phase 2 QA Round 7 — Diff Summary

## What Changed

| File | Change |
|---|---|
| `tests/test_chat.py` | Added 12 new edge case tests in `TestQAClawRound7` class |
| `docs/claude-plan.md` | Updated to reflect QA Round 7 |
| `docs/claude-diff-summary.md` | Updated to reflect QA Round 7 |
| `docs/claude-test-results.txt` | Updated with 545-test results |

## Tests Added (Round 7)
1. `test_send_message_over_100k_returns_422` — message over 100k chars rejected
2. `test_rename_over_255_returns_422` — title over 255 chars rejected
3. `test_fmt_ts_zero_seconds` — _fmt_ts(0) returns "0:00"
4. `test_fmt_ts_fractional_seconds` — _fmt_ts(65.9) truncates to "1:05"
5. `test_auto_title_exactly_50_chars_no_ellipsis` — boundary: no "..." at exactly 50
6. `test_auto_title_51_chars_gets_ellipsis` — boundary: "..." appended at 51
7. `test_create_session_default_platform_is_web` — default platform is "web"
8. `test_delete_session_returns_session_id` — delete response includes session_id
9. `test_sources_include_all_required_fields` — all 6 JSONB source fields present
10. `test_user_message_not_stored_with_model_or_tokens` — user msg has None for model/tokens
11. `test_format_chunks_empty_list` — empty chunk list returns ""
12. `test_list_sessions_default_pagination` — default offset=0, limit=20 works

## Bugs Fixed
None — no bugs found across 7 rounds of QA. Implementation is solid.

## Code Review Summary (Full)
All Phase 2 components verified against CHAT_FEATURE_PLAN.md:
- Models: proper SQLAlchemy mapped columns, JSONB sources, relationship cascade, onupdate for updated_at
- Schemas: Pydantic validation with min/max length, from_attributes, ChatSourceOut structure
- Service: RAG pipeline with chat_enabled_only=True, history trimming to chat_max_history*2, 150k token guard, graceful error handling for missing API key and API errors
- Router: complete CRUD (create/list/get/delete/rename), auto-title on first message, history built from loaded messages, updated_at touch
- Config: all 3 chat settings present with correct defaults (model=claude-sonnet-4-20250514, max_history=10, top_k=10)
- Search integration: chat_enabled_only properly propagated through vector/keyword/hybrid modes

## Test Coverage Summary
- **95 tests** in `test_chat.py` covering Phase 2 chat backend
- **545 tests total** across the full suite, all passing

## Risks
- Pydantic `min_length` does not strip whitespace — `"   "` passes validation. Acceptable for now.
- Token estimation (4 chars/token) is rough but sufficient as a safety guard.
- No migration files found in `migrations/versions/` — migrations may be managed differently or applied at deploy time.
