# T016 - Full project engineering audit

## Status
Completed — read-only audit report, 2026-05-12.

## Objective
Perform a read-only engineering evaluation of the full YouTube Transcriber project and produce a prioritized remediation roadmap.

This task was audit/planning only. No implementation fixes, DB writes, live backfills, Telegram sends, service restarts, worker-topology changes, or migrations were performed as part of T016.

## Executive summary

The project is in a much better state than the earlier stabilization phase: the core pipeline has explicit attempt metadata, lifecycle/stage separation, artifact-aware resume logic, queue routing, worker-health checks, report delivery, scan-first summary guardrails, and a broad test suite that currently collects cleanly.

The highest remaining risks are not basic syntax or missing tests. They are contract and boundary risks around when jobs are committed vs enqueued, how channel/batch dispatch interacts with the one-active-attempt model, and how local smoke/ops tests can mutate real runtime state when a service happens to be running.

Top priorities:

1. **Fix enqueue-after-commit boundaries** for retry and channel dispatch paths. Several paths call `run_pipeline` / `run_pipeline_from` before the DB transaction is committed, which can strand queued jobs if a worker sees the task before the job row is visible.
2. **Reconcile channel/batch dispatch with the active-attempt contract.** Channel processing creates pending pipeline jobs without the same active-attempt/retry-block/attempt-lineage handling used by manual submit/retry paths.
3. **Separate mutating smoke tests from the normal test suite.** `tests/test_v2_smoke.py` can hit localhost and submit a real YouTube video if the local web service is up.
4. **Add migration/model contract tests.** Alembic exists and the chain is linear, but coverage is thin outside the old chat migration test.
5. **Clean config/model naming drift and ops ergonomics.** Duplicate model settings and multiple runtime environments make it easy for Docker, native workers, tests, and scripts to disagree.

Delegated audit note: all specialist subagent slices were unusable for final synthesis. DataClaw reported no filesystem access; BuildClaw, OpsClaw, and QAClaw returned malformed/unrelated payloads instead of audit findings. This final report is therefore based on direct repo inspection and local read-only validation.

## Evidence gathered

Read-only / safe inspection performed:

- `git status --short`, `git diff --name-status`, `git ls-files --others --exclude-standard`
- Source inspection of pipeline, retry, channel dispatch, batch progress, recovery, resume, config, launchd, CI, and test files
- Alembic revision chain inspection
- Static broad-exception scan
- `find` / `grep` for pycache, venv, config, model, and Telegram import patterns
- `.venv/bin/python -m compileall -q app scripts tests` → `compile_ok`
- `.venv/bin/python pytest --collect-only -q` → `1113 tests collected in 5.48s`

Important validation boundary: no full pytest run was started for T016 because the suite includes service-dependent smoke tests that can mutate local runtime state when localhost services are up.

## Working tree separation

### T015 scan-first summary intelligence changes

Dirty/untracked files that appear to belong to T015:

- `app/report_templates/report_video.html`
- `app/services/reporting.py`
- `app/services/summarization.py`
- `app/services/telegram_messages.py`
- `app/tasks/embed.py`
- `app/services/summary_markdown.py`
- `app/services/summary_quality.py`
- `scripts/backfill_scan_first_summaries.py`
- `scripts/evaluate_scan_first_summaries.py`
- `tests/test_embed_report_notification.py`
- `tests/test_reporting.py`
- `tests/test_telegram_notify.py`
- `tests/test_scan_first_backfill_script.py`
- `tests/test_scan_first_eval_script.py`
- `tests/test_summarization_prompt.py`
- `tests/test_summary_quality.py`
- `docs/tasks/T015_scan_first_summary_intelligence.md`
- updates to `docs/PLAN.md`, `docs/CLARIFICATIONS.md`, `docs/tasks/TASK_INDEX.md`

### Pre-existing unrelated subscription dirty files

These remain separate from T015/T016 and should not be accidentally staged with audit/report work:

- `app/routers/subscriptions.py`
- `tests/test_subscriptions_api.py`

### T016 artifact

- `docs/tasks/T016_full_project_engineering_audit.md`

## Architecture map

### Runtime lanes

- **FastAPI web app:** route modules under `app/routers/*`; async DB sessions through `app.dependencies.get_db`.
- **Celery pipeline:** `app/tasks/pipeline.py` chains six ordered stages:
  1. `tasks.download_audio`
  2. `tasks.transcribe_audio`
  3. `tasks.diarize_and_align`
  4. `tasks.cleanup_transcript`
  5. `tasks.summarize_transcription`
  6. `tasks.generate_embeddings`
- **Queue routing:** `app.services.pipeline_routing.get_queue_for_task` sends stages to `audio`, `diarize`, and `post`/`celery` lanes.
- **Native worker topology:** launchd plists run three workers: audio, diarize, and post/celery through `scripts/start_worker.sh`.
- **Pipeline state contract:** `app/services/pipeline_state.py` owns lifecycle/status/stage transitions and active/terminal classifications.
- **Attempt ownership:** `app/services/pipeline_attempts.py`, migration `010`, and task payload job IDs enforce one active pipeline attempt per video.
- **Retry/recovery:** `app/services/pipeline_resume.py`, `app/services/pipeline_recovery.py`, `app/services/transient_auto_retry.py`, and `scripts/reap_stale_jobs.py` handle artifact-aware resume, bounded failures, manual review, transient retry, and stale reaping.
- **Channel backlog:** `app/routers/channels.py`, `app/services/channel_dispatcher.py`, and `app/tasks/batch_progress.py` create durable pending channel jobs and release them gradually.
- **Reports/Telegram:** `app/services/reporting.py`, `app/models/video_report.py`, `app/services/telegram_notify.py`, `app/services/telegram_messages.py`, and embed-stage completion hooks generate/send report artifacts without failing the core pipeline.
- **Subscriptions/personas/digests:** separate service/task paths now share the same DB/runtime and should be treated as sidecar subsystems with explicit failure boundaries.

## Highest-risk findings

### P1 — Celery tasks can be enqueued before the DB transaction commits

**Affected files:**

- `app/routers/jobs.py`
- `app/services/channel_dispatcher.py`
- `app/tasks/batch_progress.py`
- `app/routers/channels.py`

**Observation:**

Manual video submit commits before launching the pipeline, then stores `celery_task_id` in a second commit. Retry and channel-dispatch paths are less safe:

- `retry_job` creates/flushed a retry job, calls `run_pipeline_from(...)`, then commits.
- `promote_pending_channel_jobs` sets a job queued and calls `run_pipeline(...)` before the caller commits.
- `batch_progress._dispatch_first_pending_job` does the same inside task-layer batch advancement.

**Risk:**

A worker can receive the Celery task before the job row/status is visible in the committed DB. `get_pipeline_job_context` may then fail to load the job or see stale state and raise `Ignore()`, leaving the DB job queued with no real running chain. The stale reaper may eventually catch it, but the user-visible symptom is stranded queued work.

**Recommended remediation:**

Introduce a single pipeline-enqueue boundary with one of these contracts:

- commit queued job first, then enqueue task, then persist `celery_task_id`; or
- transactional outbox table/process; or
- explicit after-commit hook for async/sync sessions.

Use the same helper for manual submit, retry, channel dispatcher, and batch advancement.

**Suggested tests:**

- Unit test that enqueue is not called until after commit for retry and channel dispatch.
- Integration-style test where worker context cannot see an uncommitted job and verifies the new contract avoids `Ignore()`.
- Regression test for `celery_task_id` persistence when enqueue succeeds but second commit fails.

### P1 — Channel processing bypasses parts of the active-attempt/retry contract

**Affected files:**

- `app/routers/channels.py`
- `app/services/channel_dispatcher.py`
- `app/tasks/batch_progress.py`
- `app/services/pipeline_attempts.py`
- `alembic/versions/010_add_active_pipeline_attempt_unique_index.py`

**Observation:**

Manual submit/retry paths check active attempts, latest attempt, retry blocks, manual-review state, attempt number, superseding, and active-attempt `IntegrityError` recovery. `process_selected_videos` creates `pending` channel jobs directly for each selected video with `attempt_creation_reason=channel_process`, but without the same guard path.

Because migration `010` includes `pending` in the unique active-attempt index, channel processing can hit an unhandled integrity error when a selected video already has an active attempt. It also creates channel jobs with default `attempt_number=1`, which weakens lineage if a video is processed repeatedly through channel flows.

**Risk:**

- Batch creation can fail mid-request instead of skipping/reusing/reporting conflicts.
- Channel backlog can collide with manual work despite the intended manual-job protection.
- Attempt history is less trustworthy for channel-originated attempts.

**Recommended remediation:**

Create one attempt factory/service used by manual submit, retry, and channel process. It should handle:

- active-attempt reuse/skip semantics
- retry/manual-review block checks
- attempt number allocation
- attempt creation reason
- supersedes/superseded visibility
- `IntegrityError` conflict recovery
- clear per-video result objects: `created`, `already_active`, `blocked`, `skipped`, `error`

**Suggested tests:**

- Channel process skips/reports videos with active manual attempts.
- Channel process blocks manual-review latest attempts.
- Channel process increments attempt numbers after failed terminal attempts.
- Duplicate selected video IDs do not crash the whole batch.

### P1 — Mutating smoke tests are collected with the normal suite

**Affected files:**

- `tests/test_v2_smoke.py`
- `.github/workflows/unit-tests.yml`
- `scripts/run_ci_tests.sh`

**Observation:**

`tests/test_v2_smoke.py` is skipped only when `localhost:8000` is unavailable. If a developer has the local web service running, the normal suite can execute real service calls, including `POST /api/videos` with `jNQXAC9IVRw`, creating or reusing a real pipeline job.

**Risk:**

- Full test runs can mutate the developer/runtime DB.
- CI behavior differs from local behavior depending on service availability.
- Audit/QA runs can accidentally enqueue jobs even when the operator expects read-only validation.

**Recommended remediation:**

Mark smoke tests behind an explicit opt-in such as `YT_RUN_SMOKE=1` or `pytest -m smoke`, and make the default pytest invocation exclude smoke/e2e tests. Keep a separate smoke command for deliberate runtime validation.

**Suggested tests:**

- `pytest --collect-only` still sees smoke tests but marks/skips them by default.
- `scripts/run_ci_tests.sh` proves the default path cannot submit a real video.

### P1 — Migration/model contract coverage is too thin

**Affected files:**

- `alembic/versions/*.py`
- `app/models/*.py`
- `tests/test_chat.py`

**Observation:**

The Alembic chain is linear through `017`, and direct inspection did not find an obvious chain split. However, migration testing is narrow: test coverage references the old chat migration `006`, but there is no general migration-head upgrade/downgrade or SQLAlchemy-model-vs-migration drift suite.

**Risk:**

New model fields, constraints, indexes, and report tables can drift from migrations without being caught until runtime deploy.

**Recommended remediation:**

Add a migration contract test pack:

- upgrade fresh DB to head
- verify `alembic current == head`
- inspect key constraints/indexes: active-attempt unique index, report uniqueness, stage/recovery fields
- compare SQLAlchemy metadata tables/columns against inspected DB columns for core tables

**Suggested tests:**

- Fresh upgrade smoke against ephemeral Postgres.
- Constraint existence tests for `uq_jobs_pipeline_one_active_attempt` and `uq_video_reports_video_id`.
- Model/migration parity check for `jobs`, `videos`, `summaries`, `video_reports`, `channel_subscriptions`.

## Maintainability findings

### P2 — Duplicate model config names invite runtime drift

**Affected files:**

- `app/config.py`
- `app/tasks/summarize.py`
- `app/tasks/cleanup.py`
- `app/services/summarization.py`
- `app/services/digest.py`
- `scripts/backfill_scan_first_summaries.py`
- `scripts/evaluate_scan_first_summaries.py`

**Observation:**

`Settings` contains older names (`cleanup_model`, `summary_model`) and newer names (`anthropic_cleanup_model`, `anthropic_summary_model`). Different paths use different fields:

- cleanup task uses `anthropic_cleanup_model`
- summarize task uses `summary_model`
- summarization service/backfill/eval use `anthropic_summary_model`
- digest uses `anthropic_summary_model`

**Risk:**

Operators may change one env var and get different model behavior across direct pipeline summaries, scripts, digests, and backfills.

**Recommended remediation:**

Consolidate to explicit per-use-case names and leave deprecated aliases with warnings or computed compatibility only. Document env vars in README/ops docs.

### P2 — Broad `except Exception` use is common and inconsistently observable

**Affected files:**

- `app/telegram_bot.py`
- `app/routers/*`
- `app/tasks/*`
- `app/services/*`
- `scripts/*`

**Observation:**

Static scan found 66 `except Exception` occurrences. Some are correct fail-open boundaries, especially notifications/report delivery. Others convert unknown runtime problems into silent pass, generic HTTP 400s, or unstructured logs.

**Risk:**

Real regressions can be hidden, especially in Telegram, report delivery, subscriptions, cost tracking, and side-effect notification paths.

**Recommended remediation:**

Do not remove fail-open behavior blindly. Instead:

- classify each broad catch as `expected external failure`, `best-effort side effect`, or `bug mask`
- require structured logging with event name, entity IDs, exception type, and operator-visible outcome for side effects
- narrow catches where error taxonomy exists, especially provider/network failures

### P2 — Channel dispatcher and batch progress duplicate orchestration logic

**Affected files:**

- `app/services/channel_dispatcher.py`
- `app/tasks/batch_progress.py`

**Observation:**

Both modules know about batch statuses, channel job terminal states, dispatching first pending jobs, and queueing pipelines. Their semantics are not identical: one sets failed-only batches to `completed_with_errors`; the other can set `failed`.

**Risk:**

Future fixes may land in one path but not the other, causing divergent behavior depending on whether progress is advanced through dispatcher sweep or task-stage completion.

**Recommended remediation:**

Move all batch state transition and dispatch logic into `app/services/channel_dispatcher.py`. Keep `app/tasks/batch_progress.py` as a thin wrapper only.

### P2 — Report model has `report_type` but uniqueness is per-video only

**Affected files:**

- `app/models/video_report.py`
- `alembic/versions/017_add_video_reports.py`
- `app/services/reporting.py`

**Observation:**

`video_reports` has `report_type`, but both model and migration enforce uniqueness on `video_id` alone.

**Risk:**

This is fine if there is exactly one report forever, but it conflicts with the schema shape if future work adds PDF, brief, transcript, or alternate report types.

**Recommended remediation:**

Either document/enforce one report per video and remove misleading extensibility, or migrate uniqueness to `(video_id, report_type)` before multiple report types exist.

**T024 resolution:**

Current product intent is one current summary report per video. `report_type` remains as the canonical `summary_report` label, not a variant dimension. The model and migration contract tests now explicitly preserve `uq_video_reports_video_id` on `video_id` only and reject `(video_id, report_type)` uniqueness unless future multi-report work consciously changes the contract.

## Pipeline reliability and recovery findings

### What is strong

- Pipeline payload now carries both video ID and job ID.
- `get_pipeline_job_context` rejects superseded/non-active attempts and enforces artifact gates.
- Stage-specific stale timeouts exist.
- Failure signatures and manual-review quarantine exist.
- Artifact-aware resume avoids resuming into stages with missing inputs.
- Worker health distinguishes missing queue coverage from busy-but-healthy progress.

### Remaining risk areas

1. **Enqueue transaction boundary** is the top reliability issue.
2. **Channel attempt creation** needs to use the same attempt contract as manual submit/retry.
3. **Worker-health inspect blind spots** are partially handled, but runtime validation should keep testing real queue coverage after launchd/env changes.
4. **Notification/report side effects** are intentionally fail-open, but need stronger observability so failures are visible without breaking the pipeline.

## Data/model/migration findings

### Current data contract map

- `videos`: source video metadata and lifecycle status.
- `jobs`: durable pipeline attempts, attempt lineage, active/terminal status, stage tracking, recovery metadata, worker identity, artifact check result, visibility/superseding.
- `batches`: channel backlog batches and progress counters.
- `channels`: YouTube channel metadata and chat/persona flags.
- `transcriptions` / `transcription_segments`: transcript text and segment timing/speaker data.
- `summaries`: LLM summary content and token/model metadata.
- `embedding_chunks`: searchable transcript/summary chunks.
- `video_reports`: generated report artifacts and delivery status.
- `llm_usage`: cost tracking.
- `chat_sessions` / `chat_messages` / persona tables: chat and channel-persona layer.
- `channel_subscriptions`: subscription polling/compression sidecar.

### Findings

- Alembic chain is linear through `017` by direct inspection.
- Active-attempt uniqueness exists at DB level via partial index `uq_jobs_pipeline_one_active_attempt`.
- `jobs` model includes newer stage/recovery/observability fields.
- Migration coverage is not broad enough to prove model/migration parity.
- Config naming drift can change model behavior without schema drift.
- `video_reports` uniqueness should be clarified before report-type expansion.

## Test suite findings

### Strengths

- Test suite is broad: API, chat, pipeline attempts, stage gates, retry/recovery, reports, Telegram delivery, subscriptions, scan-first prompt/quality, worker health, and smoke coverage.
- Current collect-only sanity passes: `1113 tests collected in 5.48s`.
- Static compile sanity passes: `compile_ok` for `app`, `scripts`, and `tests`.
- T015-specific guardrails have focused tests around dry-run behavior, malformed-summary blocking, low-content detection, and report regeneration.

### Risks

- Smoke tests are service-dependent and can mutate local DB/runtime by submitting real videos.
- Migration tests are too narrow.
- Some tests assert legacy compatibility wrappers rather than only current public contracts, which can make refactors noisy.
- `tests/test_telegram_bot.py` imports Telegram bot code directly. This is acceptable because `python-telegram-bot` is currently a core dependency, but if Telegram is ever made optional, this test module will need skip/import guards.

## Ops/runtime findings

### What is strong

- Launchd plists now explicitly split `audio`, `diarize`, and `post,celery` workers.
- `scripts/start_worker.sh` loads `.venv-native`, `.env.native`, and Homebrew PATH.
- `scripts/worker_health.sh` checks queue coverage and has a degraded-busy path for long-running work.
- `scripts/run_ci_tests.sh` approximates GitHub Actions dependency installation.

### Risks / cleanup

- There are multiple local envs (`.venv`, `.venv-native`, `.venv314`) and runtime modes. This is workable but easy to misuse.
- Launchd and Docker use different env/url assumptions; scripts partly paper over this with `.env.native` parsing.
- `scripts/__pycache__` exists on disk but is ignored, not tracked. This is not a repo hygiene bug, just local cleanup noise.
- `scripts/run_ci_tests.sh` runs `python -m pytest -q` without excluding smoke tests. On a machine with localhost web running, it can run service-mutating tests.

## Prioritized remediation sequence

### Phase 1 — Safety/correctness first

1. **T017: Pipeline enqueue transaction boundary**
   - Priority: P1
   - Owner: BuildClaw, QAClaw
   - Files: `app/routers/jobs.py`, `app/services/channel_dispatcher.py`, `app/tasks/batch_progress.py`, `app/routers/videos.py`, `app/tasks/pipeline.py`
   - Goal: one safe commit/enqueue/celery-id contract for all pipeline starts/resumes.
   - Tests: retry enqueue ordering, channel dispatch enqueue ordering, simulated worker pre-commit visibility failure.

2. **T018: Unified pipeline attempt factory**
   - Priority: P1
   - Owner: BuildClaw, QAClaw
   - Files: `app/services/pipeline_attempts.py`, `app/routers/videos.py`, `app/routers/jobs.py`, `app/routers/channels.py`, `app/services/channel_dispatcher.py`
   - Goal: manual submit, retry, and channel process share active-attempt/retry-block/attempt-lineage semantics.
   - Tests: active conflict, manual-review block, attempt_number increments, channel duplicate selection.

3. **T019: Test-suite smoke isolation**
   - Priority: P1
   - Owner: QAClaw / SentryClaw
   - Files: `pytest.ini` or `pyproject.toml`, `tests/test_v2_smoke.py`, `.github/workflows/unit-tests.yml`, `scripts/run_ci_tests.sh`
   - Goal: default unit tests are non-mutating; smoke/e2e tests require explicit opt-in.
   - Tests: default run excludes smoke; opt-in run includes smoke.

### Phase 2 — Contract hardening

4. **T020: Alembic/model contract test pack**
   - Priority: P1/P2
   - Owner: QAClaw
   - Files: `tests/test_migrations_contract.py`, `alembic/versions/*`, `app/models/*`
   - Goal: catch migration/model drift and missing constraints before runtime.
   - Tests: fresh upgrade to head, key index/constraint checks, core table column parity.

5. **T021: Config model-name consolidation**
   - Priority: P2
   - Owner: BuildClaw
   - Files: `app/config.py`, summary/cleanup/digest/backfill/eval scripts, docs
   - Goal: one documented model setting per use case, with safe deprecated aliases if needed.
   - Tests: config defaults, env override behavior, summarize/cleanup/digest use expected fields.

6. **T022: Channel dispatcher single source of truth**
   - Priority: P2
   - Owner: BuildClaw
   - Files: `app/services/channel_dispatcher.py`, `app/tasks/batch_progress.py`, tests
   - Goal: remove duplicate batch progress/dispatch semantics.
   - Tests: failed-only batch status, completed-with-errors status, next-batch release, manual-job protection.

### Phase 3 — Observability and maintainability

7. **T023: Broad exception audit and structured side-effect logging**
   - Priority: P2
   - Owner: SentryClaw / BuildClaw
   - Files: `app/telegram_bot.py`, `app/services/telegram_notify.py`, `app/tasks/embed.py`, `app/tasks/poll_subscriptions.py`, selected routers/services
   - Goal: preserve fail-open side effects while making failures visible and classifiable.
   - Tests: notification failure does not fail pipeline but logs structured event; provider/network failures mapped to expected categories.

8. **T024: Report schema intent cleanup**
   - Priority: P2/P3
   - Owner: BuildClaw
   - Files: `app/models/video_report.py`, `app/models/video.py`, `app/services/reporting.py`, `tests/test_reporting.py`, `tests/test_migrations_contract.py`
   - Goal: resolved in favor of one current summary report per video, with `report_type` as the canonical label only.
   - Tests: report upsert/regeneration behavior and migration/model contract.

9. **T025: Ops/dev environment contract doc**
   - Priority: P3
   - Owner: OpsClaw / SentryClaw
   - Files: README/ops docs, `scripts/run_ci_tests.sh`, launchd docs, `.env` examples
   - Goal: make Docker/native/test env selection explicit and reduce operator mistakes.
   - Tests: doc commands are smoke-checked where safe.

## Blockers / unknowns preserved

- DataClaw could not inspect source because it had no read/exec tooling; its result was a blocker, not findings.
- BuildClaw, OpsClaw, and QAClaw completion payloads were malformed/unrelated and could not be used as audit evidence.
- T016 did not run live DB migrations, full pytest, service health mutations, backfills, Telegram sends, or restarts by design.
- Runtime DB state was not modified or exhaustively compared to Alembic head during T016.

## Acceptance criteria check

- Final report separates observations from recommendations: yes.
- No implementation fixes made as part of T016: yes; only this audit document was written.
- Findings are narrow enough to become follow-up tasks: yes, T017-T025 proposed.
- Roadmap prioritizes safety/correctness before cleanup/polish: yes.
- Delegated findings/blockers preserved: yes; delegated slices were explicitly marked unusable/blocked.
