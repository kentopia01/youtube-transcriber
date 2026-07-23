---
name: yt-transcribe
description: Submit YouTube videos to the local transcriber, inspect jobs, and read completed transcripts through the supported ytctl API client.
---

# yt-transcribe

Use `/Users/sentryclaw/Projects/youtube-transcriber/.venv/bin/ytctl` only. The
service is loopback-only; never query Docker or PostgreSQL directly.

Read commands: `ytctl status`, `ytctl videos --status completed`, `ytctl jobs`,
`ytctl job JOB_UUID`, and `ytctl transcript VIDEO_UUID`. Prefer `--json` for
machine consumption.

Submission starts real work. Only after an explicit user request, run
`ytctl submit URL --confirm`. Retry, cancel, and applied reconciliation must
also retain their `--confirm` flag. Return IDs and inspect with `ytctl job`;
do not create a polling loop unless the user asks you to wait.
