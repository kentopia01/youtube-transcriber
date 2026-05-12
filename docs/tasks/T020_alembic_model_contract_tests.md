# T020 - Alembic/model contract tests

## Status
Done — BuildClaw implementation and QA validation passed.

## Objective
Add safe schema-contract coverage so migration/model drift, key constraints, and required pipeline columns/indexes are caught before runtime.

## Why it matters
T016 found that the project has many migrations and model-driven runtime assumptions, but limited contract coverage that proves Alembic head and SQLAlchemy models agree on critical tables/columns/constraints. Recent T017/T018 reliability fixes depend on columns and constraints such as `jobs.attempt_number`, `jobs.current_stage`, recovery metadata, `video_reports`, and the partial unique active-attempt index.

## Source of truth
Read in order:
1. `AGENTS.md`
2. `docs/PLAN.md`
3. `docs/CLARIFICATIONS.md`
4. `docs/tasks/TASK_INDEX.md`
5. `docs/tasks/T016_full_project_engineering_audit.md`
6. this file

## In scope
- Add safe migration/model contract tests.
- Prefer non-mutating/static checks by default.
- If live DB upgrade coverage is included, it must be explicitly skipped unless an isolated test DB opt-in is provided.
- Cover critical schema contracts used by T014-T018:
  - Alembic versions form a single linear chain to head.
  - SQLAlchemy metadata contains expected critical tables.
  - `jobs` has required attempt/stage/recovery/visibility columns.
  - `videos` has dismiss fields.
  - `video_reports` table/model contract exists.
  - active pipeline attempt uniqueness index/constraint exists in migrations/metadata contract.
  - subscription/report/chat/persona tables are represented where relevant.
- Add docs/comments explaining how to run any heavier isolated migration check safely.

## Out of scope
- Do not run migrations against the live/local runtime DB.
- Do not mutate Postgres, Redis, Celery, Telegram, reports, subscriptions, or videos.
- Do not change migration history unless a test reveals a real broken import/contract that needs a minimal fix.
- Do not refactor unrelated app code.
- Do not clean up the broad dirty tree.

## Known starting points
- `alembic/versions/*`
- `alembic/env.py`
- `app/models/*`
- `tests/test_pipeline_state_contract.py`
- `tests/test_subscriptions_model.py`
- `pyproject.toml`

## Required behavior
- Default pytest remains safe/non-mutating.
- Contract tests should run without a live database unless explicitly marked/skipped for isolated DB opt-in.
- Failures should be actionable: missing migration link, missing table, missing critical column, missing constraint/index reference, or model mismatch.

## Suggested validation
Use safe commands only:

```bash
.venv/bin/python -m pytest tests/test_migrations_contract.py -q
.venv/bin/python -m pytest tests/test_pipeline_state_contract.py tests/test_subscriptions_model.py tests/test_migrations_contract.py -q
.venv/bin/python -m compileall -q tests/test_migrations_contract.py
.venv/bin/python -m pytest --collect-only -q
```

If a skipped isolated DB test is added, prove it skips by default and document the opt-in.

## Acceptance criteria
- Safe migration/model contract tests are added and pass.
- Default test collection remains non-mutating.
- T017/T018 critical schema assumptions are covered.
- No live runtime mutation occurs.
- QA validates the contract tests before T020 is marked done.

## Implementation summary
- Added `tests/test_migrations_contract.py` as a static/non-mutating migration and model contract pack.
- Covered a single linear Alembic revision chain to head.
- Covered critical SQLAlchemy metadata tables/columns for jobs, videos, reports, subscriptions, chat/persona, transcripts/summaries/embeddings, and LLM usage.
- Covered `jobs` attempt/stage/recovery/visibility fields and migration-backed indexes, including the partial unique active pipeline attempt index.
- Covered `videos` dismissal fields and `video_reports` model/migration uniqueness and delivery-index contracts.
- Kept live DB upgrade coverage out of the default suite; the test module documents that any future live migration smoke must require an isolated disposable DB and skip by default.
- Added `LlmUsage` to `app.models.__init__` so Alembic/model metadata imports include the existing `llm_usage` model table.

## Verification evidence
- PASS: `.venv/bin/python -m pytest tests/test_migrations_contract.py -q` → `20 passed in 0.40s`
- PASS: `.venv/bin/python -m pytest tests/test_pipeline_state_contract.py tests/test_subscriptions_model.py tests/test_migrations_contract.py -q` → `32 passed in 0.49s`
- PASS: `.venv/bin/python -m compileall -q tests/test_migrations_contract.py`
- PASS: `.venv/bin/python -m pytest --collect-only -q` → `1143 tests collected in 0.82s`
- PASS: `git diff --check -- app/models/__init__.py tests/test_migrations_contract.py docs/tasks/T020_alembic_model_contract_tests.md docs/tasks/TASK_INDEX.md docs/PLAN.md`
- PASS: explicit whitespace/final-newline check for untracked T020 files (`tests/test_migrations_contract.py`, `docs/tasks/T020_alembic_model_contract_tests.md`)

## QA evidence
- PASS: QA verified tests are static/non-mutating: no live Alembic upgrade, DB connection, Redis/Celery/Telegram mutation, or live service write path.
- PASS: QA verified Alembic linear-chain coverage, model table/column coverage, migration-backed pipeline index/column checks, active partial unique index contract, video dismiss fields, and video report uniqueness/delivery index.
- PASS: QA repeated required commands: `20 passed`, `32 passed`, compileall pass, `1143 tests collected`, diff-check pass.
