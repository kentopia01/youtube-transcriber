#!/usr/bin/env bash
# Check job status.
# Usage: get_status.sh <job-id>
set -euo pipefail

API="http://localhost:8000"
JOB_ID="$1"

if [[ -z "$JOB_ID" ]]; then
  echo "Usage: get_status.sh <job-id>" >&2
  exit 1
fi

curl -sf "$API/api/jobs/$JOB_ID" | python3 -m json.tool
