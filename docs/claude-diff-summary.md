# Phase 4: Telegram Bot — QAClaw QA Diff Summary

## What Changed

| File | Change |
|---|---|
| `app/telegram_bot.py` | Fixed: added missing `📹` emoji to source citations per plan spec `[📹 Title @ timestamp]` |
| `tests/test_telegram_bot.py` | Added 16 new tests (39 total), updated citation assertions for emoji fix |

## Bug Fixed
- Source citations were `[Video Title @ timestamp]` but plan specifies `[📹 Video Title @ timestamp]` — added emoji prefix in `_format_source_citation()`

## Tests Added (16 new)
- `TestFormatSourceCitation` (5): seconds-only, minutes+seconds, hours, no timestamp, missing title
- `TestVideosCommandListing` (1): listing actual videos (not just empty case)
- `TestAccessControlAdditional` (3): denied tests for /sessions, /status, /videos
- `TestHandleMessageEdgeCases` (4): empty text, error handling, auto-title, long title truncation
- `TestCreateBotApplication` (2): missing token raises ValueError, valid token creates app with 6 handlers
- `TestFormatResponseMaxSources` (1): limits output to 5 source citations

## Verification Checklist
- [x] All 5 commands registered: /start, /new, /sessions, /status, /videos
- [x] Message handler uses chat_with_context RAG pipeline
- [x] Session auto-creation per telegram chat_id
- [x] /new creates a new session
- [x] Source citation formatting: [📹 Title @ timestamp]
- [x] Message splitting at 4096 chars (newline > space > hard split)
- [x] Allowlist filtering via telegram_allowed_users
- [x] Edge cases: unauthorized user, empty library, no token, error in LLM, empty text

## Risks
- No rate limiting on Telegram messages beyond Telegram's own limits
- No typing indicator during RAG processing (could take seconds)
- Session reload in handle_message replaces the Python object — auto-title works in production (SQLAlchemy autoflush) but required careful test setup
