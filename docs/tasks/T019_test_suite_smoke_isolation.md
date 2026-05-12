# T019 - Test-suite smoke isolation

## Status
Done

## Objective
Make mutating/service-dependent smoke and e2e tests explicitly opt-in so default local/CI pytest runs cannot submit videos or mutate the live local runtime just because localhost services are running.

## Why it matters
T016 found that `tests/test_v2_smoke.py` is collected with the normal suite and only skips when localhost web is unavailable. On a developer machine with the web service running, a normal `pytest` can execute real service calls, including `POST /api/videos` with `jNQXAC9IVRw`, creating or reusing a real pipeline job.

## Source of truth
Read in order:
1. `AGENTS.md`
2. `docs/PLAN.md`
3. `docs/CLARIFICATIONS.md`
4. `docs/tasks/TASK_INDEX.md`
5. `docs/tasks/T016_full_project_engineering_audit.md`
6. this file

## In scope
- Mark smoke/e2e tests with explicit pytest markers.
- Add a default skip/guard so smoke/e2e tests do not run unless explicitly requested.
- Support an opt-in path, preferably `YT_RUN_SMOKE=1`, and document/encode it clearly.
- Update CI/local test commands so default unit runs remain non-mutating.
- Add/adjust tests or safe validation proving default collection/run does not execute smoke side effects, while opt-in selection can include smoke tests.

## Out of scope
- Do not run live smoke/e2e tests against localhost services.
- Do not submit videos, restart services, run migrations, backfills, Telegram sends, or mutate runtime state.
- Do not refactor unrelated pipeline/report/subscription code.
- Do not clean up the broad dirty tree; keep this slice narrow.

## Known starting points
- `pyproject.toml`
- `tests/conftest.py`
- `tests/test_v2_smoke.py`
- `scripts/run_ci_tests.sh`
- `.github/workflows/unit-tests.yml`

## Required behavior
- A default pytest invocation must not run smoke/e2e tests even if localhost services are available.
- Smoke/e2e tests remain discoverable and runnable through an explicit opt-in.
- The smoke file should no longer rely solely on port availability to decide whether real service calls run.
- CI's normal test command remains non-mutating.
- The opt-in command is clear for deliberate runtime validation.

## Suggested implementation
- Register `smoke` and `e2e` pytest markers.
- In `tests/conftest.py`, add a pytest option/env guard such as `--run-smoke` or `YT_RUN_SMOKE=1`; skip smoke/e2e-marked tests unless opted in.
- Mark all tests in `tests/test_v2_smoke.py` as `pytest.mark.smoke`.
- Optionally update `scripts/run_ci_tests.sh` / workflow names/messages to make the non-mutating default explicit.

## Required validation
Use safe/non-mutating commands only. Suggested:

```bash
.venv/bin/python -m pytest --collect-only tests/test_v2_smoke.py -q
.venv/bin/python -m pytest tests/test_v2_smoke.py -q
YT_RUN_SMOKE=1 .venv/bin/python -m pytest tests/test_v2_smoke.py --collect-only -q
.venv/bin/python -m pytest tests/test_channel_filters.py::TestProcessLatest -q
.venv/bin/python -m compileall -q tests/conftest.py tests/test_v2_smoke.py
```

Expected: default smoke run skips rather than issuing live service calls; opt-in collect demonstrates smoke tests are selectable without executing them.

## Implementation summary
- Registered `smoke` and `e2e` pytest markers in `pyproject.toml` and `tests/conftest.py`.
- Added pytest opt-in guards: `--run-smoke` / `YT_RUN_SMOKE=1` and `--run-e2e` / `YT_RUN_E2E=1`.
- Marked `tests/test_v2_smoke.py` as `smoke`; its localhost port guard remains as a second guard after explicit opt-in.
- Clarified CI/local script messaging that default test runs are non-mutating and smoke/e2e require explicit opt-in.

## Verification evidence
- PASS: `.venv/bin/python -m pytest --collect-only tests/test_v2_smoke.py -q` → `11 tests collected in 0.05s`
- PASS: `.venv/bin/python -m pytest tests/test_v2_smoke.py -q` → `11 skipped in 0.05s`
- PASS: `YT_RUN_SMOKE=1 .venv/bin/python -m pytest -m smoke tests/test_v2_smoke.py --collect-only -q` → `11 tests collected in 0.02s`
- PASS: `.venv/bin/python -m pytest tests/test_channel_filters.py::TestProcessLatest -q` → `10 passed in 0.80s`
- PASS: `.venv/bin/python -m pytest --collect-only -q` → `1123 tests collected in 0.59s`
- PASS: `.venv/bin/python -m compileall -q tests/conftest.py tests/test_v2_smoke.py`
- PASS: `git diff --check -- pyproject.toml tests/conftest.py tests/test_v2_smoke.py scripts/run_ci_tests.sh .github/workflows/unit-tests.yml docs/tasks/T019_test_suite_smoke_isolation.md docs/tasks/TASK_INDEX.md docs/PLAN.md`

## Acceptance criteria
- Default local/CI pytest path is non-mutating with respect to smoke/e2e tests.
- Explicit opt-in path is available and documented in code/script output or docs.
- Focused safe tests/collect-only validation pass.
- No unrelated dirty files are modified for T019.
