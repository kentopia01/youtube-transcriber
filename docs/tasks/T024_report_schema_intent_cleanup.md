# T024 - Report schema intent cleanup

## Status
Done — implementation and independent QA validation passed.

## Objective
Resolve the `video_reports.report_type` vs one-report-per-video uniqueness ambiguity before future report variants make the schema harder to change.

## Why it matters
T016 found that `video_reports` has a `report_type` column, but both the model and migration enforce uniqueness on `video_id` alone. That is coherent only if the product intent is exactly one current report per video. If future report variants are expected, uniqueness should be `(video_id, report_type)` before data depends on the current shape.

## Source of truth
Read in order:
1. `AGENTS.md`
2. `docs/PLAN.md`
3. `docs/CLARIFICATIONS.md`
4. `docs/tasks/TASK_INDEX.md`
5. `docs/tasks/T016_full_project_engineering_audit.md`
6. this file

## Decision for this slice
Prefer **one current summary report per video** for now.

Reasoning:
- Current app model relationship is `Video.report` with `uselist=False`.
- Reporting code queries by `video_id` only and overwrites/regenerates the current report.
- Digest/report delivery paths treat report state as the latest deliverable report for the video.
- Multi-report variants are not currently implemented.

So T024 should make that intent explicit and enforced in code/tests/docs, not introduce a broader multi-report migration now.

## In scope
- Add a canonical report type constant/name if useful, e.g. `SUMMARY_REPORT_TYPE`.
- Document in model/service comments that `video_reports` intentionally stores one current summary report per video.
- Ensure reporting service always uses the canonical report type.
- Keep/verify uniqueness on `video_id` only.
- Update migration/model contract tests to assert one-report-per-video intent explicitly, including the unique constraint name and canonical report type usage.
- Add/update focused reporting tests that prove regeneration updates the existing report rather than creating report variants.
- Update T016/T024 docs with the chosen intent.

## Out of scope
- Do not migrate to `(video_id, report_type)` in this slice unless direct inspection proves current product intent is multi-report.
- Do not remove `report_type` unless the change is trivial and all tests/docs are updated; keeping it as a constant historical/type label is acceptable.
- Do not alter report delivery behavior.
- Do not run live Telegram/LLM/Celery/Redis/DB mutation flows.
- Do not clean up the broad dirty tree.

## Required behavior
- There is exactly one current summary report row per video.
- `report_type` is not treated as a dimension that permits multiple rows per video.
- Regenerating a report updates the existing row.
- Schema contract tests make the intent clear so future multi-report work must consciously change model, migration, relationship, reporting queries, and tests.

## Required validation
Use safe commands only:

```bash
.venv/bin/python -m pytest tests/test_reporting.py tests/test_migrations_contract.py -q
.venv/bin/python -m pytest tests/test_embed_report_notification.py tests/test_morning_digest.py tests/test_reporting.py -q
.venv/bin/python -m compileall -q app/models/video_report.py app/models/video.py app/services/reporting.py tests/test_reporting.py tests/test_migrations_contract.py
.venv/bin/python -m pytest --collect-only -q
git diff --check -- <T024 touched files>
```

If migration files are edited, also validate Alembic revision chain/contract tests. Avoid live DB migrations unless explicitly using a disposable DB.

## Acceptance criteria
- Chosen report schema intent is explicit in code/docs/tests.
- One-report-per-video uniqueness is intentionally enforced and tested.
- Reporting regeneration/update behavior remains intact.
- No live external/runtime mutations occur.
- Safe validation passes.
- QA validates before T024 is marked done.

## Implementation notes
- Chose and documented the current product intent: `video_reports` stores exactly one current summary report per video.
- Added `SUMMARY_REPORT_TYPE = "summary_report"` as the canonical report type label.
- Updated `VideoReport` model metadata to declare the named `uq_video_reports_video_id` unique constraint explicitly on `video_id` only.
- Kept `report_type` as a canonical historical/type label; it is not a uniqueness dimension and does not permit report variants.
- Updated report generation to upsert by `video_id` only and always normalize `report.report_type` to `SUMMARY_REPORT_TYPE`.
- Added focused tests proving regeneration reuses the existing row, including when an old/different report type label is present.
- Updated migration/model contract tests to assert the one-current-summary-report contract, named unique constraint, canonical model default, non-`(video_id, report_type)` uniqueness, and `Video.report` `uselist=False` relationship intent.

## Verification evidence

Safe local validation only; no live Telegram, LLM, Celery, Redis, runtime DB, or migration mutation flows were run.

```bash
.venv/bin/python -m pytest tests/test_reporting.py tests/test_migrations_contract.py -q
# 27 passed in 0.37s

.venv/bin/python -m pytest tests/test_embed_report_notification.py tests/test_morning_digest.py tests/test_reporting.py -q
# 20 passed in 0.44s

.venv/bin/python -m compileall -q app/models/video_report.py app/models/video.py app/services/reporting.py tests/test_reporting.py tests/test_migrations_contract.py
# passed (no output)

.venv/bin/python -m pytest --collect-only -q
# 1168 tests collected in 0.64s

git diff --check -- app/models/video_report.py app/models/video.py app/services/reporting.py tests/test_reporting.py tests/test_migrations_contract.py docs/tasks/T024_report_schema_intent_cleanup.md docs/tasks/T016_full_project_engineering_audit.md docs/tasks/TASK_INDEX.md
# tracked-file whitespace check passed (no output)

for f in tests/test_migrations_contract.py docs/tasks/T016_full_project_engineering_audit.md docs/tasks/T024_report_schema_intent_cleanup.md; do
  rc=0
  git diff --check --no-index -- /dev/null "$f" || rc=$?
  if [ "$rc" -gt 1 ]; then exit "$rc"; fi
done
# untracked-file whitespace check passed (no output)
```

## Independent QA evidence

- PASS: Independent QA verified `SUMMARY_REPORT_TYPE = "summary_report"` is canonical and used consistently.
- PASS: Independent QA verified `video_reports` has named uniqueness on `video_id` only (`uq_video_reports_video_id`) and rejects `(video_id, report_type)` uniqueness.
- PASS: Independent QA verified `Video.report` remains `uselist=False`, `report_type` is documented as a label rather than a variant dimension, and report regeneration reuses the existing row.
- PASS: Independent QA repeated validation: reporting + migration contract `27 passed`, embed/digest/reporting regression `20 passed`, compileall pass, collect-only `1168 collected`, diff-check pass, untracked file whitespace/final-newline checks pass.
- PASS: No Alembic/live migration edits or runtime Telegram/LLM/Celery/Redis/DB mutation flows were run.
