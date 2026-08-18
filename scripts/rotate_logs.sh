#!/usr/bin/env bash
# Rotate split worker logs. Keep the last 30 days by default.
# Run daily via cron or manually.
set -euo pipefail

LOG_DIR="${YT_WORKER_LOG_DIR:-/tmp/yt-worker}"
KEEP_DAYS="${YT_WORKER_LOG_KEEP_DAYS:-30}"

shopt -s nullglob
LOG_FILES=()
for CANDIDATE in "$LOG_DIR"/yt-worker-*.log; do
  # Exclude dated backups from the set of live launchd files.
  if [[ "$(basename "$CANDIDATE")" =~ \.20[0-9]{2}-[0-9]{2}-[0-9]{2}\.log$ ]]; then
    continue
  fi
  LOG_FILES+=("$CANDIDATE")
done

if [[ ${#LOG_FILES[@]} -eq 0 ]]; then
  echo "No split worker log files found at $LOG_DIR/yt-worker-*.log"
  exit 0
fi

DATE=$(date +%Y-%m-%d)
ROTATED=0

for LOG_FILE in "${LOG_FILES[@]}"; do
  STEM="${LOG_FILE%.log}"
  BACKUP="${STEM}.${DATE}.log"

  # launchd holds the file descriptor, so use copytruncate semantics. The
  # source is truncated only after the backup operation succeeds.
  if [[ -f "$BACKUP" ]]; then
    cat "$LOG_FILE" >> "$BACKUP"
  else
    cp "$LOG_FILE" "$BACKUP"
  fi
  : > "$LOG_FILE"
  ROTATED=$((ROTATED + 1))
done

# Clean only dated split-worker backups; never match current worker logs.
find "$LOG_DIR" -type f -name "yt-worker-*.20??-??-??.log*" -mtime "+${KEEP_DAYS}" -delete 2>/dev/null

# Compress logs older than 1 day
find "$LOG_DIR" -type f -name "yt-worker-*.20??-??-??.log" -mtime +1 -exec gzip {} \; 2>/dev/null

echo "Rotated $ROTATED split worker log(s); retention=${KEEP_DAYS}d"
