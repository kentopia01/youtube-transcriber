# Phase 4: Telegram Bot — Implementation Plan

## Goal
Add a Telegram bot that lets users chat with their video transcript library via the same RAG pipeline used by the web chat UI.

## Assumptions
- Phases 1-3 (toggles, chat backend, web UI) are complete and working
- The bot runs as a standalone process alongside the web app
- It shares the same Postgres database and chat service
- `python-telegram-bot>=21.0` is the library of choice

## Steps

1. **Config** — Add `telegram_bot_token`, `telegram_allowed_users`, `database_url_native` to `app/config.py`
2. **Dependency** — Add `python-telegram-bot>=21.0` to `pyproject.toml` main deps
3. **Bot module** (`app/telegram_bot.py`):
   - `/start` — welcome message
   - `/new` — create new chat session (platform='telegram')
   - `/sessions` — list last 10 sessions for this Telegram chat
   - `/status` — show chat-enabled video count + total
   - `/videos` — list chat-enabled video titles
   - Regular messages — route through `chat_with_context()` RAG pipeline
   - Access control via `telegram_allowed_users` allowlist
   - Response formatting with source citations `[Video Title @ timestamp]`
   - Message splitting at 4096 char Telegram limit
4. **Entry point** — `scripts/run_telegram_bot.py` standalone script
5. **launchd plist** — `com.sentryclaw.yt-telegram-bot.plist` template
6. **Tests** — 23 tests covering commands, access control, message handling, formatting, splitting
7. **README** — Setup instructions, commands reference, launchd installation
