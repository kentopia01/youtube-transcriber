#!/usr/bin/env bash
# Native macOS Celery worker startup script.
# Uses MLX Whisper with Metal acceleration on Apple Silicon.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Activate venv
source .venv-native/bin/activate

# Load native environment
set -a
source .env.native
set +a

# Ensure Homebrew CLI tools are visible under launchd, especially ffmpeg/ffprobe for yt-dlp.
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"

# Ensure data and log directories exist
mkdir -p data/audio data/models /tmp/yt-worker

CELERY_HOSTNAME="${CELERY_HOSTNAME:-native-worker@%h}"
CELERY_QUEUES="${CELERY_QUEUES:-audio,diarize,post,celery}"
CELERY_LOG_LEVEL="${LOG_LEVEL:-info}"

exec celery -A app.tasks.celery_app worker \
    --loglevel="$CELERY_LOG_LEVEL" \
    --pool=solo \
    --hostname="$CELERY_HOSTNAME" \
    -Q "$CELERY_QUEUES"
