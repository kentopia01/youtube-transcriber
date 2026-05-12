# T022 - Channel dispatcher single source of truth

## Status
Done — implementation and QA validation passed.

## Objective
Move channel batch progress/state-transition and next-job dispatch semantics into `app/services/channel_dispatcher.py`, leaving `app/tasks/batch_progress.py` as a thin compatibility wrapper.

## Why it matters
T016 found duplicate orchestration logic between `app/services/channel_dispatcher.py` and `app/tasks/batch_progress.py`. Both know about batch statuses, terminal job states, next-batch release, and pipeline enqueueing. Their semantics can diverge: for example, one path normalized all-failed batches to `completed_with_errors` while another could mark them `failed`.

## Source of truth
Read in order:
1. `AGENTS.md`
2. `docs/PLAN.md`
3. `docs/CLARIFICATIONS.md`
4. `docs/tasks/TASK_INDEX.md`
5. `docs/tasks/T016_full_project_engineering_audit.md`
6. this file

## In scope
- Centralize batch status refresh, terminal-state handling, next-batch release, and pending channel job dispatch in `app/services/channel_dispatcher.py`.
- Keep `app/tasks/batch_progress.py` as a thin wrapper that delegates to the dispatcher service.
- Preserve T017 commit-before-publish enqueue boundary.
- Preserve T018 channel attempt semantics.
- Preserve non-fatal handling when advancing the next batch fails to enqueue; failure must not poison/retry the just-completed current pipeline job.
- Make all-failed batch semantics explicit and consistent. Prefer dispatcher semantics unless a test/product reason says otherwise.
- Update tests to assert the single source of truth and behavior.

## Out of scope
- Do not change channel submission/discovery behavior except as required by centralized dispatch semantics.
- Do not run live Celery/Redis/Postgres/Telegram flows.
- Do not mutate runtime services.
- Do not perform broad cleanup of unrelated dirty files.
- Do not alter T017/T018 contracts.

## Known starting points
- `app/services/channel_dispatcher.py`
- `app/tasks/batch_progress.py`
- `app/tasks/embed.py` and other task callers of `update_batch_progress_and_maybe_advance`
- `tests/test_channel_dispatcher.py`
- `tests/test_task_orchestration.py`
- `tests/test_channel_filters.py`

## Required behavior
- `batch_progress.update_batch_progress_and_maybe_advance(db, batch_id)` remains import-compatible but delegates to `channel_dispatcher`.
- Dispatcher-owned logic should handle:
  - missing batch → no-op
  - non-terminal batch → no dispatch
  - terminal current batch → refresh counts/status/completed_at
  - next pending batch → mark running and dispatch first eligible pending channel job
  - enqueue failure for next job → mark next job failure/recovery through enqueue helper, refresh next batch, log structured warning, return no dispatched job, and do not raise into current pipeline stage
- Batch terminal status should be consistent across dispatcher sweeps and task-stage completion.
- Manual jobs must continue to block channel backlog promotion where applicable.

## Required validation
Use safe commands only:

```bash
.venv/bin/python -m pytest tests/test_channel_dispatcher.py tests/test_task_orchestration.py -q
.venv/bin/python -m pytest tests/test_channel_filters.py tests/test_channel_dispatcher.py tests/test_task_orchestration.py tests/test_channel_submit*.py -q
.venv/bin/python -m compileall -q app/services/channel_dispatcher.py app/tasks/batch_progress.py tests/test_channel_dispatcher.py tests/test_task_orchestration.py
.venv/bin/python -m pytest --collect-only -q
git diff --check -- <T022 touched files>
```

If there is no `tests/test_channel_submit*.py`, do not fail solely for that; include the relevant channel/router tests instead.

## Acceptance criteria
- Batch progress/dispatch logic has one implementation owner in `channel_dispatcher.py`.
- `batch_progress.py` is a thin wrapper.
- Divergent all-failed/completed-with-errors behavior is resolved and tested.
- T017/T018 enqueue/attempt invariants remain covered by focused tests.
- Safe validation passes.
- QA validates before T022 is marked done.

## Implementation summary
- Moved task-layer batch advancement into `app/services/channel_dispatcher.py` via dispatcher-owned `update_batch_progress_and_maybe_advance`.
- Reduced `app/tasks/batch_progress.py` to an import-compatible compatibility wrapper.
- Centralized next-batch lookup, first pending job dispatch, canonical terminal batch status, and non-fatal next-batch enqueue failure handling in the dispatcher.
- Preserved the T017 `enqueue_pipeline_job_after_commit` boundary for channel promotion and next-batch advancement.
- Kept direct channel backlog dispatch failures fatal to the caller while keeping next-batch advancement failures non-fatal to the just-completed current pipeline job.
- Made all-failed batches resolve to `completed_with_errors` consistently and added focused coverage.

## Verification evidence
- PASS: `.venv/bin/python -m pytest tests/test_channel_dispatcher.py tests/test_task_orchestration.py -q` → `10 passed in 0.88s`
- PASS: `.venv/bin/python -m pytest tests/test_channel_filters.py tests/test_channel_dispatcher.py tests/test_task_orchestration.py -q` → `38 passed in 3.72s`
- PASS: `.venv/bin/python -m compileall -q app/services/channel_dispatcher.py app/tasks/batch_progress.py tests/test_channel_dispatcher.py tests/test_task_orchestration.py` → no output
- PASS: `.venv/bin/python -m pytest --collect-only -q` → `1161 tests collected in 1.52s`
- PASS: `git diff --check -- app/services/channel_dispatcher.py app/tasks/batch_progress.py tests/test_channel_dispatcher.py tests/test_task_orchestration.py docs/PLAN.md docs/tasks/TASK_INDEX.md` plus explicit untracked-file check for `docs/tasks/T022_channel_dispatcher_single_source_of_truth.md` via `git diff --check --no-index -- /dev/null docs/tasks/T022_channel_dispatcher_single_source_of_truth.md` → no output

## QA evidence
- PASS: QA verified `batch_progress.py` is a thin compatibility wrapper delegating to `channel_dispatcher.update_batch_progress_and_maybe_advance`.
- PASS: QA verified dispatcher owns refresh, terminal batch status, next-batch lookup, first pending job dispatch, enqueue failure handling, and commit-before-publish via `enqueue_pipeline_job_after_commit`.
- PASS: QA verified direct backlog enqueue failure remains fatal, next-batch enqueue failure is suppressed/logged and marks the next job failed, all-failed batches resolve to `completed_with_errors`, and manual-job blocking remains covered.
- PASS: QA repeated focused validation: `10 passed`, `38 passed`, compileall pass, `1161 tests collected`, diff-check pass, explicit untracked doc whitespace/final-newline check pass.
