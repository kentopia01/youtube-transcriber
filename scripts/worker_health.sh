#!/usr/bin/env bash
# Check if the native Celery worker is healthy.
# Returns 0 if healthy or busy-but-healthy, 1 if unhealthy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
QUIET=0
RESTART=0

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

cd "$PROJECT_ROOT"
set -a
source .env.native
set +a
source .venv-native/bin/activate

if python - <<'PY' >/dev/null 2>&1
from app.tasks.celery_app import celery
res = celery.control.inspect(timeout=3).ping() or {}
raise SystemExit(0 if res else 1)
PY
then
  log "HEALTH_OK: Worker responded to Celery ping"
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
  log "HEALTH_OK: Worker appears busy but healthy on a long-running active stage"
  exit 0
fi

if [[ "$RESTART" -eq 1 ]]; then
  log "HEALTH_WARN: Restarting native worker"
  launchctl kickstart -k "gui/$(id -u)/com.sentryclaw.yt-worker"
  sleep 2
  if python - <<'PY' >/dev/null 2>&1
from app.tasks.celery_app import celery
res = celery.control.inspect(timeout=5).ping() or {}
raise SystemExit(0 if res else 1)
PY
  then
    log "HEALTH_RECOVERED: Worker restarted successfully"
    exit 0
  fi
fi

log "HEALTH_FAIL: Worker did not respond to ping and no busy-but-healthy active jobs were detected"
exit 1
