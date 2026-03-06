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

# Query Postgres directly (running in Docker)
FILTER=""
if [[ -n "$STATUS" ]]; then
  FILTER="WHERE v.status = '$STATUS'"
fi

docker exec youtube-transcriber-postgres-1 psql -U transcriber -d transcriber -t -A -F '|' -c "
SELECT v.id, v.youtube_video_id, v.title, v.status, v.duration_seconds,
       CASE WHEN t.id IS NOT NULL THEN 'yes' ELSE 'no' END as has_transcript,
       CASE WHEN s.id IS NOT NULL THEN 'yes' ELSE 'no' END as has_summary
FROM videos v
LEFT JOIN transcriptions t ON t.video_id = v.id
LEFT JOIN summaries s ON s.video_id = v.id
$FILTER
ORDER BY v.created_at DESC
LIMIT $LIMIT;
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
