# T051 - Catch-up Runner Hardening

## Status

done

## Objective

Make the local YouTube catch-up runner resilient to one bad candidate so unattended backlog release keeps moving.

## In Scope

- Treat `/api/videos` submit failures as per-candidate skips instead of crashing the whole runner.
- Persist skipped candidate metadata in runner state: batch number, channel, YouTube ID, title, reason, and timestamp.
- Save batch progress after each submit/skip so a later crash does not replay already-handled items.
- Summarize submitted and skipped counts in logs and Telegram notifications.
- Use the runtime video-duration cap from env/config instead of the stale hardcoded 150 minute cap.

## Out of Scope

- Changing channel selection strategy.
- Increasing worker concurrency.
- Retrying private/deleted/future-premiere videos immediately.
- Editing secret-bearing native env files.

## Acceptance

- Future premieres, unavailable videos, and other submit-time HTTP failures do not terminate the runner.
- The runner still stops for real downstream pipeline blockers detected from fresh failed jobs.
- Focused compile/runtime validation passes without exposing secrets.

## Validation

- `/Users/sentryclaw/.openclaw/workspace/scripts/yt_catchup_batch_runner.py` compiles with the native project interpreter.
- Live runner restart submitted Batch 8 with 5 videos and skipped future premiere `FFU45SKaeYM` without crashing.
- Runner state persisted `last_batch_number=8` plus one skipped candidate with a retry-after timestamp.
