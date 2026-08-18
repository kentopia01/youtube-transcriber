# T083 - Due-Poll Cadence and Split-Worker Log Retention

## Status

Done (2026-08-06).

## Objective

Remove schedule drift and false-green log maintenance from the native operating
workflow.

## In scope

- Run subscription polling hourly while preserving per-subscription due checks.
- Rotate each actual `yt-worker-*.log` file using copy/truncate semantics.
- Retain 30 days and compress rotated logs after one day.
- Make rotation paths/retention testable through explicit environment overrides.
- Convert the rotation cron from an agent turn to a deterministic command.
- Focused cadence and shell-script tests.

## Out of scope

- Changing subscription `poll_frequency_hours` values.
- Releasing current failed jobs.
- Moving Redis/Postgres out of Docker.
- Changing launchd worker queue topology.

## Drift guards and stop conditions

- Hourly scheduling must not poll a 24-hour subscription hourly.
- Rotation must not truncate a worker log unless its backup copy succeeded.
- Never delete non-worker files from the log directory.

## Done criteria

- A manual poll offset no longer causes an approximately 45-hour gap.
- Audio/post/diarize logs each rotate and remain writable.
- Old rotated worker logs expire after 30 days; current logs are preserved.
- Cron payloads are deterministic and post-edit inspection proves the schedules.

## Validation

- Focused hourly cadence and isolated log-rotation tests passed.
- The subscription poll cron now runs hourly while preserving due checks.
- Log rotation is a deterministic command against the actual split-worker logs,
  and the outcome watchdog runs every 30 minutes.
