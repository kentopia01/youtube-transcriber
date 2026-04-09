# T005 - Pipeline stabilization Phase 1.5: DB-level one-active-attempt enforcement and concurrent test

## Status
Done

## Objective
Close the concurrency hole left after Phase 1 by enforcing one-active-attempt-per-video at the database level and validating it with at least one concurrent integration test.

## Why it matters
Phase 1 added application-level guards, but QA correctly flagged that concurrent submit/retry requests could still race. This phase hardens the attempt model so the system cannot create multiple active attempts for the same video under concurrent load.

## Scope
- Add DB-level enforcement for one active attempt per video.
- Define clearly which statuses count as active.
- Update retry/submit flows if needed to handle DB-level conflicts cleanly.
- Add at least one concurrent integration test that proves the race is blocked.

## Out of scope
- Parallel worker architecture
- Throughput improvements
- Broad UI work
- Later-phase observability improvements

## Constraints
- Keep changes surgical and compatible with Phase 1.
- Prefer explicit DB enforcement over application-only heuristics.
- Handle conflict paths gracefully rather than surfacing opaque DB crashes.

## Done criteria
- Database-level rule prevents more than one active attempt per video.
- Retry/submit flows behave predictably when the DB rule is hit.
- A concurrent test proves the race is closed.
- Migration is included if required.

## Validation
- BuildClaw implemented against this file.
- Added DB-level partial unique index `uq_jobs_pipeline_one_active_attempt` for active pipeline attempts.
- Submit/retry now catch active-attempt unique conflicts and return the active attempt payload instead of surfacing a DB exception.
- Added concurrent integration coverage in `tests/test_pipeline_attempts_concurrency.py`.

### Verification evidence
- `.venv314/bin/python -m pytest tests/test_jobs_retry.py tests/test_video_submit_supersede.py tests/test_pipeline_attempts_concurrency.py -q` → `13 passed`
