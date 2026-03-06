#!/usr/bin/env bash
# Native macOS Celery worker startup script.
# Uses MLX Whisper with Metal acceleration on Apple Silicon.
# Concurrency=1 because MLX uses the Metal GPU — parallel workers would compete.

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

# Ensure data directories exist
mkdir -p data/audio data/models

# Start Celery worker
exec celery -A app.tasks.celery_app worker \
    --loglevel="${LOG_LEVEL:-info}" \
    --pool=solo \
    --hostname="native-worker@%h" \
    -Q celery
