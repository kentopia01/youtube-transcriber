#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_ROOT="${YT_BACKUP_DIR:-$REPO_ROOT/data/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="$BACKUP_ROOT/$STAMP"

mkdir -p "$TARGET"
cd "$REPO_ROOT"

docker compose exec -T postgres pg_dump \
  -U "${POSTGRES_USER:-transcriber}" \
  -d "${POSTGRES_DB:-transcriber}" \
  --format=custom --no-owner --no-privileges > "$TARGET/database.dump"

if [[ -d data/reports ]]; then
  tar -czf "$TARGET/reports.tar.gz" -C data reports
fi

(
  cd "$TARGET"
  shasum -a 256 database.dump > SHA256SUMS
  if [[ -f reports.tar.gz ]]; then
    shasum -a 256 reports.tar.gz >> SHA256SUMS
  fi
)

printf '{"created_at":"%s","database":"%s","reports":"%s"}\n' \
  "$STAMP" "database.dump" "$([[ -f "$TARGET/reports.tar.gz" ]] && printf 'reports.tar.gz' || printf '')" \
  > "$TARGET/manifest.json"

echo "$TARGET"
