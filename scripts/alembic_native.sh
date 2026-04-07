#!/usr/bin/env bash
# Run Alembic with native macOS/local Postgres env.
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

exec "$ROOT/.venv/bin/alembic" "$@"
