# T025 - Final full-suite release hygiene

## Status
Done — final default full test suite passed

## Objective
Run final non-mutating release hygiene after T017-T024 and get the default full test suite to completion.

## Scope
- Inspect final dirty-tree state.
- Run safe static gates (`compileall`, `git diff --check`, collect-only).
- Run the full default pytest suite (`.venv/bin/python -m pytest -q`).
- Keep smoke/e2e tests opt-in unless explicitly running a controlled live smoke later.
- Record failures and fix regressions if the full suite exposes them.

## Out of scope
- Do not run live Telegram/LLM/Celery/Redis/DB mutations during default full-suite validation.
- Do not commit or push unless Ken explicitly asks.
- Do not run opt-in smoke/live tests until the default full suite is green.

## Required validation
```bash
.venv/bin/python -m compileall -q app scripts tests
.venv/bin/python -m pytest --collect-only -q
git diff --check
.venv/bin/python -m pytest -q
```

## Acceptance criteria
- Default full pytest suite completes.
- Any failures are fixed or clearly blocked with exact cause.
- Final status summarizes what is done, what still needs release management, and recommended dry-run/live-smoke next step.

## Validation evidence

Safe non-mutating release hygiene completed:

```bash
.venv/bin/python -m compileall -q app scripts tests
# passed, no output

.venv/bin/python -m pytest --collect-only -q
# 1168 tests collected

git diff --check
# passed, no output

.venv/bin/python -m pytest -q
# 1157 passed, 11 skipped in 4.68s
```

Notes:
- The 11 skipped tests are the opt-in smoke/e2e tests isolated by T019.
- No opt-in live smoke was run during this default full-suite gate.
- Repo remains intentionally dirty from T015-T025 local work; no commit/push was performed.
