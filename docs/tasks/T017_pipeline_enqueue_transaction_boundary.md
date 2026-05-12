# T017 - Pipeline enqueue transaction boundary

## Status
Done — implemented locally, 2026-05-12.

## Objective
Fix the pipeline start/resume transaction boundary so Celery tasks are not published before the database state they depend on is committed and visible.

## Why it matters
T016 found that retry and channel-dispatch paths can call `run_pipeline` / `run_pipeline_from` while the queued job state is still inside an uncommitted transaction. A worker can receive the task first, fail to see the job row or current status, and `Ignore()` the chain. The DB can then show a queued job with no live Celery execution until stale recovery catches it.

## Source of truth
Read in order:
1. `AGENTS.md`
2. `docs/PLAN.md`
3. `docs/CLARIFICATIONS.md`
4. `docs/tasks/TASK_INDEX.md`
5. `docs/tasks/T016_full_project_engineering_audit.md`
6. this file

## In scope
- Design and implement one safe enqueue boundary for all pipeline starts/resumes.
- Cover at minimum:
  - manual video submit path
  - job retry path
  - channel dispatcher promotion path
  - task-layer batch advancement path
- Ensure DB state is committed before Celery workers can depend on it.
- Preserve or improve persistence of `celery_task_id`.
- Add regression tests for enqueue ordering and failure handling.
- Keep behavior compatible with existing active-attempt, stage-gate, resume, and queue-routing contracts.

## Out of scope
- Do not redesign the active-attempt factory; that is T018.
- Do not change worker topology, launchd, queues, Redis, Docker, or migrations unless a minimal migration is explicitly proven necessary.
- Do not run live backfills, Telegram sends, runtime restarts, or mutating smoke tests.
- Do not touch unrelated subscription dirty files: `app/routers/subscriptions.py`, `tests/test_subscriptions_api.py`.
- Do not include formatting-only churn.

## Current risk areas from T016

### Retry path
`app/routers/jobs.py` creates/flushed a retry job, calls `run_pipeline_from(...)`, then commits. The worker may see the Celery message before the retry job is committed.

### Channel dispatcher path
`app/services/channel_dispatcher.py` marks a pending channel job queued and calls `run_pipeline(...)` before the caller commits.

### Batch progress path
`app/tasks/batch_progress.py` dispatches the first pending job in the next batch before the surrounding task transaction commits.

### Manual submit path
`app/routers/videos.py` is safer because it commits before launching and persists `celery_task_id` afterward, but it should be aligned with the shared helper/contract if practical.

## Recommended implementation shape
Prefer a narrow service/helper that centralizes the enqueue lifecycle, for example:

1. Persist/commit the job in an active queued state.
2. Publish the Celery chain with the committed `job_id` payload.
3. Persist `celery_task_id` in a follow-up transaction.
4. If Celery publish fails, mark the job failed or leave a clear queued/enqueue_failed state that the operator/retry path can recover from.

A transactional outbox or after-commit hook is acceptable if it stays narrow and well-tested, but avoid broad architecture churn.

## Required tests / validation
Minimum expected tests:

- Retry endpoint does not call `run_pipeline_from` until after commit.
- Channel dispatcher promotion does not publish a Celery chain before queued job state is committed/visible.
- Batch advancement uses the same safe enqueue helper or equivalent ordering.
- Celery publish failure leaves a recoverable, operator-visible state.
- Existing queue-routing/stage-gate tests still pass.

Suggested focused commands:

```bash
.venv/bin/python -m pytest \
  tests/test_pipeline_attempts.py \
  tests/test_channel_dispatcher.py \
  tests/test_jobs.py \
  tests/test_channel_filters.py \
  -q
```

If exact test filenames differ, select the closest existing retry/channel/dispatcher/stage-gate packs and document what was run.

## Acceptance criteria
- No Celery task is intentionally published before the job row/status it depends on is committed.
- All pipeline entry points use the same contract or an explicitly documented equivalent.
- Regression tests prove ordering and publish-failure behavior.
- No unrelated T015/subscription dirty changes are modified.
- T016's top P1 finding is closed or any remaining edge is explicitly documented for T018.

## Implementation summary
- Added `app/services/pipeline_enqueue.py` as the narrow shared contract: commit queued job state, publish Celery work, then persist `celery_task_id` in a follow-up commit.
- On Celery publish failure, the helper marks the job `failed` at the queued stage with an operator-visible error message and raises `PipelineEnqueueError`.
- Aligned manual submit, user retry, transient auto-retry, channel dispatcher promotion, and task-layer batch advancement to use the same commit-before-publish boundary.
- `process_selected_videos` now commits durable pending channel jobs before invoking the dispatcher.

## Verification evidence
- PASS: `.venv/bin/python -m pytest tests/test_jobs_retry.py tests/test_video_submit_supersede.py tests/test_channel_dispatcher.py tests/test_task_orchestration.py tests/test_transient_auto_retry.py tests/test_stage_gates.py tests/test_pipeline_chain.py tests/test_channel_filters.py tests/test_pipeline_attempts_concurrency.py -q` → `73 passed in 0.77s`
- PASS: `.venv/bin/python -m pytest tests/test_task_orchestration.py tests/test_channel_filters.py::TestProcessLatest -q` → `10 passed in 0.79s`
- PASS: `.venv/bin/python -m compileall -q app/tasks/batch_progress.py app/routers/channels.py tests/test_task_orchestration.py tests/test_channel_filters.py`
- PASS: `git diff --check -- app/tasks/batch_progress.py app/routers/channels.py tests/test_task_orchestration.py tests/test_channel_filters.py`
- Earlier PASS from BuildClaw/main: compileall and `git diff --check` for the broader T017 file set.

## QA follow-up fix
- QAClaw found that task-layer batch advancement could let a next-batch enqueue failure escape into the current stage task, causing a just-completed/failed current video to be retried or reclassified because the next batch could not publish.
- Fixed `app/tasks/batch_progress.py` so `PipelineEnqueueError` from next-batch dispatch is non-fatal to the current pipeline task. The target next-batch job remains marked failed/recoverable by the enqueue helper, batch progress is refreshed best-effort, and the current task continues.
- Fixed `app/routers/channels.py` so dispatcher enqueue failure after channel process creation returns HTTP 503 instead of an unhandled 500.

## T018 remaining scope
- T018 should still redesign/unify active-attempt creation semantics for channel/manual/retry flows, including channel conflict result reporting, attempt-number allocation, and manual-review skip behavior. T017 did not change that factory contract.
