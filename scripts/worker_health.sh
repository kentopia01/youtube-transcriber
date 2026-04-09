#!/usr/bin/env bash
# Check if the native Celery worker topology is healthy.
# Returns 0 if required queues are covered, or if work is actively progressing on a long stage.
# Returns 1 if unhealthy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
QUIET=0
RESTART=0
REQUIRED_QUEUES="${REQUIRED_QUEUES:-audio,diarize,post,celery}"
SERVICES=("com.sentryclaw.yt-worker" "com.sentryclaw.yt-worker-audio" "com.sentryclaw.yt-worker-diarize")

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quiet)
      QUIET=1
      shift
      ;;
    --restart)
      RESTART=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

log() {
  if [[ "$QUIET" -eq 0 ]]; then
    echo "$@"
  fi
}

check_queue_coverage() {
  python - <<'PY'
from app.tasks.celery_app import celery
import os

required = {q.strip() for q in os.environ.get('REQUIRED_QUEUES', '').split(',') if q.strip()}
insp = celery.control.inspect(timeout=5)
queues_by_worker = insp.active_queues() or {}
if not queues_by_worker:
    raise SystemExit(1)
covered = set()
for queues in queues_by_worker.values():
    for q in queues or []:
        name = q.get('name')
        if name:
            covered.add(name)
missing = required - covered
if missing:
    raise SystemExit(1)
raise SystemExit(0)
PY
}

cd "$PROJECT_ROOT"
set -a
source .env.native
set +a
source .venv-native/bin/activate
export REQUIRED_QUEUES

if check_queue_coverage >/dev/null 2>&1; then
  log "HEALTH_OK: Required queues are covered by live Celery workers"
  exit 0
fi

if python - <<'PY' >/dev/null 2>&1
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.job import Job
from app.services.worker_health import any_busy_healthy_jobs

engine = create_engine(settings.database_url_sync)
with Session(engine) as db:
    jobs = db.execute(
        select(Job).where(Job.job_type == 'pipeline', Job.status.in_(['pending', 'queued', 'running']))
    ).scalars().all()
    raise SystemExit(0 if any_busy_healthy_jobs(jobs) else 1)
PY
then
  log "HEALTH_OK: Worker topology appears busy but healthy on a long-running active stage"
  exit 0
fi

if [[ "$RESTART" -eq 1 ]]; then
  log "HEALTH_WARN: Restarting native worker topology"
  for service in "${SERVICES[@]}"; do
    if launchctl print "gui/$(id -u)/$service" >/dev/null 2>&1; then
      launchctl kickstart -k "gui/$(id -u)/$service" || true
    elif [[ -f "$HOME/Library/LaunchAgents/$service.plist" ]]; then
      launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/$service.plist" >/dev/null 2>&1 || true
      launchctl kickstart -k "gui/$(id -u)/$service" || true
    fi
  done
  sleep 3
  if check_queue_coverage >/dev/null 2>&1; then
    log "HEALTH_RECOVERED: Required queues restored successfully"
    exit 0
  fi
fi

log "HEALTH_FAIL: Required queues are not covered and no busy-but-healthy active jobs were detected"
exit 1
