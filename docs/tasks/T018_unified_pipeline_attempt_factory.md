# T018 - Unified pipeline attempt factory

## Status
Done — implemented locally, 2026-05-12.

## Objective
Unify pipeline attempt creation across manual video submit, user retry, transient auto-retry, and channel processing so all entry points share the same active-attempt, manual-review, attempt-number, lineage, and conflict-reporting semantics.

## Why it matters
T017 fixed when Celery work is published relative to committed DB state. It intentionally did not redesign how attempts are created. T016/T017 preserved a remaining risk: channel processing still has weaker semantics than manual submit/retry for active conflicts, manual-review blocks, attempt-number allocation, and per-video conflict reporting.

## Source of truth
Read in order:
1. `AGENTS.md`
2. `docs/PLAN.md`
3. `docs/CLARIFICATIONS.md`
4. `docs/tasks/TASK_INDEX.md`
5. `docs/tasks/T016_full_project_engineering_audit.md`
6. `docs/tasks/T017_pipeline_enqueue_transaction_boundary.md`
7. this file

## In scope
- Introduce a narrow shared attempt-creation service/factory used by:
  - manual video submit / resubmit
  - user retry
  - transient auto-retry
  - channel process job creation
- Preserve the T017 commit-before-publish enqueue boundary.
- Normalize:
  - active-attempt conflict detection and response
  - manual-review retry blocking
  - attempt-number allocation
  - supersedes/superseded lineage where applicable
  - attempt creation reason
  - per-video channel process results (`created`, `already_active`, `blocked`, `skipped`, `error`)
- Add tests for manual, retry, transient, and channel process behavior.

## Out of scope
- Do not change worker topology, launchd, queues, Redis, Docker, or migrations unless a minimal migration is explicitly proven necessary.
- Do not run live backfills, Telegram sends, runtime restarts, or mutating smoke tests.
- Do not touch unrelated subscription dirty files: `app/routers/subscriptions.py`, `tests/test_subscriptions_api.py`.
- Do not refactor report/summary/T015 files.
- Do not broaden into T019 smoke-test isolation.

## Known starting points
- `app/services/pipeline_attempts.py`
- `app/routers/videos.py`
- `app/routers/jobs.py`
- `app/routers/channels.py`
- `app/services/transient_auto_retry.py`
- `app/services/pipeline_enqueue.py`
- `alembic/versions/010_add_active_pipeline_attempt_unique_index.py`

## Required behavior
- Manual submit still returns the active attempt on conflict rather than creating duplicate active work.
- Retry respects manual-review blocks and supersedes failed attempts consistently.
- Transient auto-retry uses the same attempt-number and active-attempt guard logic as user retry.
- Channel process should not let one active/manual-review conflict crash the whole batch; it should return explicit per-video results and create jobs only for eligible videos.
- Any `IntegrityError` from `uq_jobs_pipeline_one_active_attempt` should be recovered into a clear conflict result where practical.

## Required tests / validation
Minimum expected tests:
- Manual submit active-attempt conflict remains stable.
- User retry attempt_number increments and blocks manual-review latest attempts.
- Transient auto-retry uses the same attempt allocation/active guard behavior.
- Channel process skips/reports videos with active attempts instead of crashing.
- Channel process blocks/reports manual-review latest attempts.
- Duplicate selected channel videos do not crash the whole request.
- T017 focused enqueue tests still pass.

Suggested focused commands:

```bash
.venv/bin/python -m pytest \
  tests/test_video_submit_supersede.py \
  tests/test_jobs_retry.py \
  tests/test_transient_auto_retry.py \
  tests/test_channel_filters.py \
  tests/test_pipeline_attempts_concurrency.py \
  -q
```

If exact test names differ, use the closest safe focused tests and document them.

## Acceptance criteria
- All pipeline attempt entry points share one attempt-creation contract or documented narrow wrappers around it.
- Channel processing reports per-video conflict/block outcomes instead of failing the whole batch for expected conflicts.
- T017 enqueue boundary remains intact.
- Focused tests pass.
- No unrelated dirty files are modified.

## Implementation summary
- Extended `app/services/pipeline_attempts.py` into the shared attempt factory/allocation contract for async and sync paths.
- Manual video submit/resubmit, user retry, transient auto-retry, and channel process job creation now use shared allocation/create helpers for active guard, manual-review block, attempt numbering, creation reason, and lineage.
- Preserved T017 commit-before-publish behavior by keeping enqueue publication in `pipeline_enqueue.py` after attempt creation and committed queued/pending state.
- Channel processing now preflights selected videos, dedupes duplicate selected IDs, creates jobs only for eligible videos, and returns per-video `video_results` with `created`, `already_active`, `blocked`, `skipped`, or `error` statuses.
- Channel-created attempts now receive allocated attempt numbers and supersede/hide prior failed attempts via the same visibility path used by manual/retry flows.
- QA blocker fix: active-attempt unique-index conflicts during attempt creation are isolated with a nested transaction/savepoint when the real SQLAlchemy session supports it, preventing one channel item conflict from rolling back earlier batch/job work in the same request.
- QA follow-up fix: channel batches are created after successful attempt creation and are sized from actual created jobs, so late conflicts cannot commit empty batches or over-count `total_videos`.

## Verification evidence
- PASS: `.venv/bin/python -m pytest tests/test_channel_filters.py::TestProcessLatest::test_process_late_active_conflict_does_not_rollback_prior_created_job tests/test_channel_filters.py::TestProcessLatest -q` → `10 passed in 0.82s`
- PASS: `.venv/bin/python -m pytest tests/test_video_submit_supersede.py tests/test_jobs_retry.py tests/test_transient_auto_retry.py tests/test_channel_filters.py tests/test_pipeline_attempts_concurrency.py -q` → `55 passed in 1.06s`
- PASS: `.venv/bin/python -m pytest tests/test_jobs_retry.py tests/test_video_submit_supersede.py tests/test_channel_dispatcher.py tests/test_task_orchestration.py tests/test_transient_auto_retry.py tests/test_stage_gates.py tests/test_pipeline_chain.py tests/test_channel_filters.py tests/test_pipeline_attempts_concurrency.py -q` → `78 passed in 0.73s`
- PASS: `.venv/bin/python -m compileall -q app/services/pipeline_attempts.py app/routers/videos.py app/routers/jobs.py app/routers/channels.py app/services/transient_auto_retry.py tests/test_channel_filters.py tests/test_transient_auto_retry.py tests/test_pipeline_attempts_concurrency.py`
- PASS: `git diff --check -- app/services/pipeline_attempts.py app/routers/videos.py app/routers/jobs.py app/routers/channels.py app/services/transient_auto_retry.py tests/test_channel_filters.py tests/test_transient_auto_retry.py tests/test_pipeline_attempts_concurrency.py docs/tasks/T018_unified_pipeline_attempt_factory.md docs/tasks/TASK_INDEX.md docs/PLAN.md`

## Notes
- No DB migration, worker topology change, runtime restart, live backfill, Telegram send, or smoke/full pytest run was performed.
- Pre-existing unrelated dirty subscription and T015 report/summary files were not touched for T018.
