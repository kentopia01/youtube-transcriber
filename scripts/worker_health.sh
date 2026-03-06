#!/usr/bin/env bash
# Check if the native Celery worker is healthy.
# Returns 0 if healthy, 1 if unhealthy.
# Usage: worker_health.sh [--restart] [--quiet]
set -euo pipefail

RESTART=false
QUIET=false
PLIST_LABEL="com.sentryclaw.yt-worker"
WORKER_LOG="/tmp/yt-worker/yt-worker.log"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --restart) RESTART=true; shift ;;
    --quiet|-q) QUIET=true; shift ;;
    *) shift ;;
  esac
done

log() { $QUIET || echo "$@"; }

# Check 1: Is the launchd job running?
if ! launchctl list | grep -q "$PLIST_LABEL"; then
  log "❌ Worker launchd job not loaded"
  if $RESTART; then
    log "🔄 Loading and starting worker..."
    launchctl load ~/Library/LaunchAgents/${PLIST_LABEL}.plist 2>/dev/null
    launchctl start "$PLIST_LABEL"
    sleep 3
  fi
  exit 1
fi

# Check 2: Is the worker process alive?
WORKER_PID=$(launchctl list | grep "$PLIST_LABEL" | awk '{print $1}')
if [[ "$WORKER_PID" == "-" ]] || [[ -z "$WORKER_PID" ]]; then
  log "❌ Worker process not running (launchd shows no PID)"
  if $RESTART; then
    log "🔄 Restarting worker..."
    launchctl kickstart -kp "gui/$(id -u)/$PLIST_LABEL"
    sleep 3
  fi
  exit 1
fi

# Check 3: Can we ping Celery via Redis?
CELERY_PING=$(cd ~/Projects/youtube-transcriber && source .venv-native/bin/activate && \
  REDIS_URL=redis://localhost:6379/0 celery -A app.tasks.celery_app inspect ping --timeout=5 2>/dev/null || true)

if echo "$CELERY_PING" | grep -q "pong"; then
  log "✅ Worker healthy (PID: $WORKER_PID, Celery responds to ping)"
  exit 0
else
  log "⚠️  Worker process running (PID: $WORKER_PID) but Celery not responding"
  
  # Check for recent crashes in log
  if [[ -f "$WORKER_LOG" ]]; then
    RECENT_ERRORS=$(tail -20 "$WORKER_LOG" | grep -c "SIGABRT\|WorkerLostError\|CRITICAL\|Traceback" || true)
    if [[ "$RECENT_ERRORS" -gt 0 ]]; then
      log "🔥 Found $RECENT_ERRORS error indicators in recent logs"
    fi
  fi

  if $RESTART; then
    log "🔄 Restarting worker..."
    launchctl kickstart -kp "gui/$(id -u)/$PLIST_LABEL"
    sleep 3
  fi
  exit 1
fi
