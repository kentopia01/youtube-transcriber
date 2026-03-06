# Phase 4: Telegram Bot — Diff Summary

## What Changed

| File | Change |
|---|---|
| `app/config.py` | Added `telegram_bot_token`, `telegram_allowed_users`, `database_url_native` settings |
| `pyproject.toml` | Added `python-telegram-bot>=21.0` to main dependencies |
| `app/telegram_bot.py` | **NEW** — Full Telegram bot with 5 commands + message handler |
| `scripts/run_telegram_bot.py` | **NEW** — Standalone entry point for the bot |
| `com.sentryclaw.yt-telegram-bot.plist` | **NEW** — launchd service template |
| `tests/test_telegram_bot.py` | **NEW** — 23 tests for all bot functionality |
| `README.md` | Added Telegram Bot section + config vars |

## Why
Phase 4 of the Chat Feature Plan — enables chatting with transcripts via Telegram using the same RAG pipeline as the web UI.

## Risks
- Bot token must be kept secret (in `.env`, not committed)
- `database_url_native` defaults to localhost — must match actual DB host when running outside Docker
- No rate limiting on Telegram messages (relies on Telegram's own rate limits)
- Long RAG responses may take several seconds; no typing indicator shown

## Plan Deviations
- Added `database_url_native` config for the bot's DB connection (bot runs natively, not in Docker, so needs localhost URL)
