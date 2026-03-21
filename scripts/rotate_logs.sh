#!/usr/bin/env bash
# Rotate worker logs. Keep last 7 days of logs.
# Run daily via cron or manually.
set -euo pipefail

LOG_DIR="/tmp/yt-worker"
LOG_FILE="$LOG_DIR/yt-worker.log"
KEEP_DAYS=7

if [[ ! -f "$LOG_FILE" ]]; then
  echo "No log file found at $LOG_FILE"
  exit 0
fi

# Rotate using copytruncate pattern.
# launchd holds the file descriptor — mv would orphan it.
# Instead: copy contents to backup, then truncate the original in-place.
DATE=$(date +%Y-%m-%d)
BACKUP="$LOG_DIR/yt-worker.${DATE}.log"

if [[ -f "$BACKUP" ]]; then
  # Already rotated today, append
  cat "$LOG_FILE" >> "$BACKUP"
else
  cp "$LOG_FILE" "$BACKUP"
fi

# Truncate in-place so launchd's fd keeps writing to the same file
: > "$LOG_FILE"

# Clean old logs
find "$LOG_DIR" -name "yt-worker.*.log" -mtime "+${KEEP_DAYS}" -delete 2>/dev/null

# Compress logs older than 1 day
find "$LOG_DIR" -name "yt-worker.*.log" -mtime +1 -not -name "*.gz" -exec gzip {} \; 2>/dev/null

echo "Rotated: $(du -sh "$BACKUP" | cut -f1) → $BACKUP"
