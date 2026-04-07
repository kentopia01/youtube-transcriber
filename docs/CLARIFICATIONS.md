# Clarifications

## Workflow rule
For serious implementation work in this repo, the execution source of truth is:
- `docs/PLAN.md`
- `docs/CLARIFICATIONS.md`
- `docs/tasks/TASK_INDEX.md`
- task files under `docs/tasks/`

BuildClaw should implement against these files, not a chat brief alone. QAClaw should validate against the same files.

## Current clarifications

### Superseded failed jobs and retention
- Superseded failed jobs should be hidden from the default failed-job UI.
- A failed job is superseded when a newer job for the same video is created through retry or failed-video re-submit.
- Hidden superseded failed jobs should be retained for 14 days, then deleted by cleanup.
- Cleanup should delete only hidden, superseded, failed jobs, not active, visible, or completed jobs.
- Dry-run must be available before enabling automated cleanup.

### Rollout safety
- Do a dry-run cleanup before enabling scheduled deletion.
- Keep ingestion dedupe behavior unchanged for non-failed existing videos.
- Use targeted tests plus QA validation before rollout.
