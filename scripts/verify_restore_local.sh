#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: scripts/verify_restore_local.sh /absolute/path/to/backup" >&2
  exit 2
fi

BACKUP_DIR="$1"
if [[ "$BACKUP_DIR" != /* || ! -d "$BACKUP_DIR" || ! -f "$BACKUP_DIR/database.dump" ]]; then
  echo "Backup must be an existing absolute directory containing database.dump" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERIFY_DB="yt_restore_verify_$(date -u +%Y%m%d%H%M%S)_$$"
DB_USER="${POSTGRES_USER:-transcriber}"

if [[ ! -f "$BACKUP_DIR/SHA256SUMS" ]]; then
  echo "Backup is missing SHA256SUMS" >&2
  exit 2
fi
(
  cd "$BACKUP_DIR"
  shasum -a 256 -c SHA256SUMS
)

cleanup() {
  cd "$REPO_ROOT"
  docker compose exec -T postgres dropdb -U "$DB_USER" --if-exists "$VERIFY_DB" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

cd "$REPO_ROOT"
docker compose exec -T postgres createdb -U "$DB_USER" "$VERIFY_DB"
docker compose exec -T postgres pg_restore -U "$DB_USER" -d "$VERIFY_DB" --no-owner --no-privileges < "$BACKUP_DIR/database.dump"
VIDEO_COUNT="$(docker compose exec -T postgres psql -U "$DB_USER" -d "$VERIFY_DB" -tAc 'SELECT COUNT(*) FROM videos')"
ALEMBIC_REVISION="$(docker compose exec -T postgres psql -U "$DB_USER" -d "$VERIFY_DB" -tAc 'SELECT version_num FROM alembic_version')"

printf 'restore_verified database=%s videos=%s alembic=%s\n' "$VERIFY_DB" "$VIDEO_COUNT" "$ALEMBIC_REVISION"
