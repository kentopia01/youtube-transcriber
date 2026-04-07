#!/usr/bin/env bash
# Wrapper for hidden superseded failed job cleanup using native macOS/local Postgres env.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env.native" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env.native"
  set +a
fi

if [[ -z "${DATABASE_URL_SYNC:-}" && -n "${DATABASE_URL:-}" ]]; then
  export DATABASE_URL_SYNC="${DATABASE_URL/postgresql+asyncpg:/postgresql+psycopg2:}"
fi

DB_URL="${DATABASE_URL_SYNC:?DATABASE_URL_SYNC is required}"
DB_URL="${DB_URL/postgresql+psycopg2:/postgresql:}"

exec "$ROOT/.venv/bin/python" "$ROOT/scripts/reap_hidden_superseded_failed_jobs.py" --db-url "$DB_URL" "$@"
