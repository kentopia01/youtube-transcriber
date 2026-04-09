# Clarifications

## Workflow rule
For serious implementation work in this repo, the execution source of truth is:
- `AGENTS.md`
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

### Current hotfix scope
- Fixes for the current GitHub Actions red build and the diarization `AudioDecoder` runtime error should be kept surgical.
- The 3 earlier user-requested videos should be retried only after the runtime fix is applied.
- Do not claim the transcription workflow is healthy until those retried jobs are verified.

### Phase 1 stabilization scope
- The current superseding-job churn is treated as a pipeline design problem, not just an operator problem.
- Phase 1 should prioritize attempt lineage, one-active-attempt enforcement, artifact-aware resume planning, and safe audio retention for retryable execution.
- Speed/parallelism changes are intentionally deferred until the retry/resume model is trustworthy.

### Phase 1.5 stabilization scope
- The one-active-attempt rule should be enforced at the database level, not just in application code.
- Submit/retry conflict paths should fail predictably and return the active attempt instead of creating duplicate active attempts.
- Add at least one concurrent integration test that proves the race window is closed.

### Phase 2 stabilization scope
- Separate lifecycle status from stage/progress semantics so active, terminal, and superseded attempts are unambiguous.
- Current stage should be explicitly tracked for active pipeline jobs.
- Recovery/retry logic should rely on explicit state rather than parsing ambiguous progress messages.

### Phase 3 stabilization scope
- Recovery should be bounded, stage-aware, and predictable.
- Repeated identical failures should not create indefinite attempt churn.
- Slow-but-active jobs should be distinguished from truly stale jobs before automatic recovery or reaping occurs.
- Quarantine/manual-review paths are acceptable when repeated failure signatures persist.

### Post-Phase-3 sequencing
- After T007, prioritize observability before throughput work.
- Record structured attempt-creation reasons, worker identity/activity, and artifact-check results before splitting queues.
- Worker health should distinguish busy-but-healthy from unhealthy before any throughput/concurrency tuning.
- Do not increase concurrency on the existing single queue as a substitute for proper workload separation.
