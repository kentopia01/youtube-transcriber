#!/usr/bin/env bash
# Start the Telegram chat bot natively on macOS.
# Uses the same .env.native as the Celery worker for DB and API credentials.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

mkdir -p /tmp/yt-chatbot

# Activate native venv (has sentence-transformers for RAG search)
source .venv-native/bin/activate

# Load native environment
set -a
source .env.native
set +a

exec python -m app.telegram_bot
