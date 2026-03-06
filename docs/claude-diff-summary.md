# Phase 4: Telegram Bot — Diff Summary

## What Changed

| File | Change |
|---|---|
| `app/config.py` | Added `database_url_native` setting (token + allowlist already existed) |
| `app/telegram_bot.py` | Updated: use native DB URL, removed unused imports, added `__main__` block |
| `scripts/start_telegram_bot.sh` | **NEW** — Shell script to start the bot with venv + env |
| `com.sentryclaw.yt-chatbot.plist` | **NEW** — launchd service plist for auto-start |
| `tests/test_telegram_bot.py` | Already existed — 23 tests all passing |
| `README.md` | Added Telegram Bot section with setup, commands, launchd instructions + `DATABASE_URL_NATIVE` config var |

## Why
Phase 4 of the Chat Feature Plan — enables chatting with transcripts via Telegram using the same RAG pipeline as the web UI.

## Risks
- Bot token must be kept secret (in `.env`, not committed)
- `database_url_native` defaults to localhost — must match actual DB host when running outside Docker
- No rate limiting on Telegram messages (relies on Telegram's own rate limits)
- Long RAG responses may take several seconds; no typing indicator shown

## Plan Deviations
- Added `database_url_native` config for the bot's DB connection (bot runs natively, not in Docker, so needs localhost URL)
