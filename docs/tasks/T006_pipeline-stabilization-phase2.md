# T006 - Pipeline stabilization Phase 2: separate execution status from stage/progress

## Status
Done

## Objective
Make pipeline execution state trustworthy by separating terminal/job lifecycle status from current processing stage and progress reporting.

## Why it matters
Current jobs can present contradictory states like queued jobs with mid-pipeline progress messages. Operators cannot reliably tell whether a job is waiting, actively running, failed, or superseded. This phase makes state transitions explicit so recovery logic and UI can reason safely.

## Scope
- Separate lifecycle status from current stage/progress semantics.
- Define clearly which statuses are terminal vs active.
- Introduce explicit stage tracking for pipeline phases (for example: download, transcribe, diarize, align, summarize, embed).
- Improve heartbeat/progress updates so active jobs can be distinguished from stale ones.
- Update relevant schemas/tests so state reporting is consistent.

## Out of scope
- Throughput/parallelism changes
- Broad UI redesign beyond what is necessary for safe state reporting
- Later-phase observability work not required for state correctness

## Constraints
- Keep changes compatible with Phase 1 and 1.5.
- Prefer explicit machine-safe state transitions over inferred meaning from progress messages.
- Do not mix unrelated repo cleanup into this phase.

## Done criteria
- Lifecycle status is no longer overloaded to represent stage.
- Current stage is explicitly tracked for active pipeline jobs.
- Active vs terminal vs superseded attempts are unambiguous.
- Progress/state tests cover the new contract.
- Retry/recovery logic can rely on the new state model without ambiguity.

## Validation
- BuildClaw implemented against this file.
- QAClaw validates against this file.

### Verification evidence
- Added explicit lifecycle+stage transition guardrails in `app/services/pipeline_state.py`.
- Added/updated contract tests in `tests/test_pipeline_state_contract.py`.
- Removed progress-percentage stage inference from `app/templates/partials/job_status.html` and queue summary rendering.
- `.venv/bin/pytest -q tests/test_pipeline_state_contract.py tests/test_task_orchestration.py tests/test_jobs_retry.py tests/test_video_submit_supersede.py` → `22 passed`
