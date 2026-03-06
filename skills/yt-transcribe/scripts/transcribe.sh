#!/usr/bin/env bash
# Submit a YouTube video for transcription and wait for completion.
# Usage: transcribe.sh <youtube-url> [--no-wait] [--timeout 600]
set -euo pipefail

API="http://localhost:8000"
URL=""
WAIT=true
TIMEOUT=600

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-wait) WAIT=false; shift ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    -*) echo "Unknown flag: $1" >&2; exit 1 ;;
    *) URL="$1"; shift ;;
  esac
done

if [[ -z "$URL" ]]; then
  echo "Usage: transcribe.sh <youtube-url> [--no-wait] [--timeout 600]" >&2
  exit 1
fi

# Submit
RESP=$(curl -sf -X POST "$API/api/videos" \
  -H "Content-Type: application/json" \
  -d "{\"url\": \"$URL\"}")

JOB_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
VIDEO_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['video_id'])")
STATUS=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")

echo "Submitted: job_id=$JOB_ID video_id=$VIDEO_ID status=$STATUS"

if [[ "$STATUS" == "existing" ]]; then
  echo "Video already processed. Fetching transcription..."
  curl -sf "$API/api/transcriptions/$VIDEO_ID" | python3 -m json.tool
  exit 0
fi

if [[ "$WAIT" == false ]]; then
  echo '{"job_id":"'"$JOB_ID"'","video_id":"'"$VIDEO_ID"'","status":"queued"}'
  exit 0
fi

# Poll until done
ELAPSED=0
INTERVAL=5
while [[ $ELAPSED -lt $TIMEOUT ]]; do
  JOB=$(curl -sf "$API/api/jobs/$JOB_ID")
  JOB_STATUS=$(echo "$JOB" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  PROGRESS=$(echo "$JOB" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('progress_message',''))" 2>/dev/null || true)

  if [[ "$JOB_STATUS" == "completed" ]]; then
    echo "Job completed. Fetching transcription..."
    curl -sf "$API/api/transcriptions/$VIDEO_ID" | python3 -m json.tool
    exit 0
  elif [[ "$JOB_STATUS" == "failed" ]]; then
    echo "Job failed." >&2
    echo "$JOB" | python3 -m json.tool >&2
    exit 1
  fi

  echo "Status: $JOB_STATUS — $PROGRESS (${ELAPSED}s elapsed)"
  sleep "$INTERVAL"
  ELAPSED=$((ELAPSED + INTERVAL))
done

echo "Timed out after ${TIMEOUT}s. Job still running: $JOB_ID" >&2
exit 2
