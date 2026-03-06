#!/usr/bin/env python3
"""Standalone entry point for the Telegram bot.

Run from the project root:
    .venv/bin/python scripts/run_telegram_bot.py

The bot connects to the same database as the web app.
Configure TELEGRAM_BOT_TOKEN and optionally TELEGRAM_ALLOWED_USERS in .env.

For native macOS usage, also set DATABASE_URL to point to localhost:
    DATABASE_URL=postgresql+asyncpg://transcriber:transcriber@localhost:5432/transcriber
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.telegram_bot import run_bot  # noqa: E402

if __name__ == "__main__":
    run_bot()
