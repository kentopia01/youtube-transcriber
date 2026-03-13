#!/usr/bin/env bash
# List transcribed videos from the database.
# Usage: list_videos.sh [--limit 20] [--status completed]
set -euo pipefail

LIMIT=20
STATUS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit) LIMIT="$2"; shift 2 ;;
    --status) STATUS="$2"; shift 2 ;;
    -*) echo "Unknown flag: $1" >&2; exit 1 ;;
    *) shift ;;
  esac
done

# Validate LIMIT is a positive integer
if ! [[ "$LIMIT" =~ ^[0-9]+$ ]] || [[ "$LIMIT" -lt 1 ]] || [[ "$LIMIT" -gt 1000 ]]; then
  echo "Error: --limit must be a positive integer (1-1000)" >&2
  exit 1
fi

# Validate STATUS is a safe alphanumeric value (no SQL injection)
if [[ -n "$STATUS" ]] && ! [[ "$STATUS" =~ ^[a-zA-Z_]+$ ]]; then
  echo "Error: --status must be alphabetic (e.g. completed, failed, pending)" >&2
  exit 1
fi

# Build parameterized query — use psql variables for safe interpolation
FILTER=""
if [[ -n "$STATUS" ]]; then
  FILTER="WHERE v.status = :'status_val'"
fi

# Use psql variable binding for safe parameter passing
docker exec youtube-transcriber-postgres-1 psql -U transcriber -d transcriber -t -A -F '|' \
  --variable="status_val=$STATUS" \
  --variable="limit_val=$LIMIT" \
  -c "
SELECT v.id, v.youtube_video_id, v.title, v.status, v.duration_seconds,
       CASE WHEN t.id IS NOT NULL THEN 'yes' ELSE 'no' END as has_transcript,
       CASE WHEN s.id IS NOT NULL THEN 'yes' ELSE 'no' END as has_summary
FROM videos v
LEFT JOIN transcriptions t ON t.video_id = v.id
LEFT JOIN summaries s ON s.video_id = v.id
$FILTER
ORDER BY v.created_at DESC
LIMIT :'limit_val';
" | python3 -c "
import sys
rows = [line.strip().split('|') for line in sys.stdin if line.strip()]
if not rows:
    print('No videos found.')
    sys.exit(0)
headers = ['id','youtube_id','title','status','duration_s','transcript','summary']
print('| ' + ' | '.join(headers) + ' |')
print('|' + '|'.join(['---'] * len(headers)) + '|')
for r in rows:
    # Truncate title
    if len(r) >= 7:
        r[2] = r[2][:60] + ('...' if len(r[2]) > 60 else '')
        print('| ' + ' | '.join(r[:7]) + ' |')
"
