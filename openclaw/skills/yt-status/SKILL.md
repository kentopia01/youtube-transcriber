---
name: yt-status
description: Inspect the local YouTube Transcriber service, workers, warnings, queue, subscriptions, and Reader activity without mutating them.
---

# yt-status

Use `/Users/sentryclaw/Projects/youtube-transcriber/.venv/bin/ytctl` with
`status`, `workers`, `warnings`, `jobs`, `subscriptions`, or `reader`. This
skill is read-only. Explain structured warnings and their next actions. Never
retry, cancel, submit, reconcile, reset, or redeliver unless the user separately
authorizes that mutation.
