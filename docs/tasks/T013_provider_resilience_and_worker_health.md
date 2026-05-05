# T013 — Provider Resilience + Worker Health + Transient Auto-Retry

## Objective

Implement the YouTube Transcriber side of the 2026-05-05 failure-hardening plan:

1. Cleanup/summarization provider resilience for transient Anthropic/API/network failures.
2. Worker health v2 that distinguishes busy solo workers from dead/missing queue coverage.
3. Safe auto-retry sweep for transient cleanup/summarize failures.

## Source of truth

Read in order:

1. `AGENTS.md`
2. `docs/PLAN.md`
3. `docs/CLARIFICATIONS.md`
4. `docs/tasks/TASK_INDEX.md`
5. this file
6. Workspace incident plan: `/Users/sentryclaw/.openclaw/workspace/plans/2026-05-05-failure-hardening-implementation-plan.md`

## Background

On 2026-05-05, 7 pipeline jobs failed at `cleanup` with failure signature:

`cleanup|APIConnectionError|connection error.`

Manual retry resumed from `cleanup_transcript`; 6 of 7 recovered quickly. This confirms the failure was transient/provider connectivity, not corrupt input artifacts.

The native worker health script also reported unhealthy because `post/celery` queue coverage was missing from Celery inspect while the post worker was actively processing cleanup tasks. This is a false-negative / blind spot.

## In scope

### A. Cleanup/summarization retry resilience

- Identify Anthropic/API retryable exception classes currently used in cleanup and summarization paths.
- Add bounded retry/backoff with jitter for transient connection errors, timeouts, 429, and 5xx where missing.
- Preserve manual-review / permanent failure behavior for non-transient errors.
- Ensure failure signatures remain stage-aware and useful.

### B. Worker health v2

- Update `scripts/worker_health.sh` and/or `app/services/worker_health.py` so health has multiple signals:
  - Celery inspect queue coverage when available.
  - LaunchAgent/service state if needed.
  - DB active job freshness.
  - recent worker log progress for post worker if Celery inspect cannot see it.
- Treat an actively progressing post worker as healthy/degraded-busy, not dead.
- Avoid restart loops while real progress is being made.

### C. Auto-retry transient failures

- Add a safe retry sweep for recent failed pipeline jobs whose failure signature is known transient:
  - cleanup/summarize API connection errors
  - timeouts / retryable provider failures
- Must respect existing retry guardrails:
  - do not retry manual-review jobs
  - do not create duplicate active attempts
  - do not retry deterministic permanent failures
  - bounded retry count
- Prefer reusing existing retry planning / artifact-aware resume logic.

## Out of scope

- Major UI redesign.
- New queues or throughput topology changes.
- Changing subscription polling semantics.
- Broad model provider replacement.
- Backup/OpenClaw cron changes; those are separate tasks.

## Done criteria

- Focused tests added/updated for retryable provider failures.
- Focused tests added/updated for worker health busy-vs-dead classification.
- Focused tests added/updated for transient auto-retry guardrails.
- Existing subscription API fix remains intact.
- Relevant focused test suite passes.
- A live/dry-run command proves the recovery path does not enqueue duplicates and recognizes current state.

## Validation commands

Suggested minimum:

```bash
cd ~/Projects/youtube-transcriber
source .venv-native/bin/activate
pytest tests/test_reap_stale_jobs.py tests/test_jobs_retry.py tests/test_worker_health.py tests/test_subscriptions_api.py -q
bash scripts/worker_health.sh
```

If a new script is added, include a `--dry-run` validation command.

## Implementation notes — 2026-05-05

Status: done.

Implemented:
- Shared provider retry taxonomy/decorator for cleanup and summarization (`APIConnectionError`, `APITimeoutError`, 408/429, and 5xx with bounded jittered backoff).
- Summarization task-level retry now only retries provider-transient errors; permanent failures still record stage-aware pipeline failures.
- Shared artifact-aware resume planner for manual retry and auto-retry paths.
- Worker health v2 detects degraded-busy post work via active DB job freshness and recent post-worker log progress when Celery inspect coverage is incomplete.
- Safe transient retry sweep at `scripts/auto_retry_transient_failures.py`, defaulting to dry-run-friendly planning and preserving manual-review, duplicate-active-attempt, latest-attempt, non-transient, age, and retry-count guardrails.

Validation evidence:

```bash
source .venv-native/bin/activate && pytest tests/test_provider_retry.py tests/test_transient_auto_retry.py tests/test_worker_health.py -q
# 19 passed in 0.60s

source .venv-native/bin/activate && pytest tests/test_reap_stale_jobs.py tests/test_jobs_retry.py tests/test_worker_health.py tests/test_subscriptions_api.py tests/test_provider_retry.py tests/test_transient_auto_retry.py tests/test_transcript_cleanup.py tests/test_cleanup_task.py -q
# 62 passed in 1.61s

bash scripts/worker_health.sh
# HEALTH_OK: Required queues are covered by live Celery workers

source .venv-native/bin/activate && python scripts/auto_retry_transient_failures.py --dry-run --limit 10 --max-age-hours 24
# Summary: skipped=10
```
