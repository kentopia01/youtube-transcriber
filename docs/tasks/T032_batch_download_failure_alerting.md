# T032 - Batch Download Failure Alerting

## Status
Done

## Objective
Alert operators when multiple videos fail with the same download-stage YouTube 403 signature in one recent window.

## Scope
- Add a script to summarize recent download-stage 403 failures.
- Include cookie health and yt-dlp version in the diagnostic payload.
- Add Telegram notification rendering for the degraded-download event.

## Out of scope
- Changing every pipeline failure notification.
- Sending alerts for one-off single video failures.

## Done criteria
- Threshold-based checker exits non-zero when threshold is met.
- Optional Telegram notify path uses a concise diagnostic event.

## Validation
- Renderer tests and script dry-run against local DB.
