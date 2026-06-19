# T035 - Repo cleanup after download hardening

## Status
Done

## Objective
Return the repository to a clean, reviewable state after the YouTube download hardening work by separating and validating the pre-existing summary-quality changes, then removing or ignoring generated OpenClaw workspace artifacts that do not belong in the app repo.

## Scope
- Validate the existing T026/T027 summary-quality change set before committing it.
- Commit the T026/T027 summary-quality work separately from the YouTube download hardening commit.
- Remove or ignore generated OpenClaw workspace files from the app repo root after confirming they are not app-owned.
- Leave the committed YouTube download hardening work unchanged.
- Keep a follow-up note to measure summary-quality impact later.

## Out of scope
- Pushing commits to a remote.
- Restarting workers or changing runtime topology.
- Reworking the T026/T027 product behavior beyond fixes required to pass validation.
- Deleting app-owned docs, runtime data, or operator state.

## Validation plan
- Run focused tests for the dirty T026/T027 paths.
- Run compile checks for touched app and script modules.
- Run `git diff --check`.
- Confirm `git status --short` is clean or contains only intentionally ignored runtime artifacts.

## Verification
- PASS: `.venv/bin/python -m pytest tests/test_reporting.py tests/test_summary_quality.py tests/test_summarization_prompt.py tests/test_scan_first_backfill_script.py tests/test_scan_first_eval_script.py tests/test_telegram_notify.py tests/test_embed_report_notification.py tests/test_model_config_paths.py tests/test_pipeline_recovery.py -q` -> `82 passed`.
- PASS: `.venv/bin/python -m compileall app/services app/tasks scripts`.
- PASS: `git diff --check`.

## Impact measurement follow-up
- Later impact check should compare report quality before/after T026/T027 using recent completed videos: quality-gate pass rate, average summary/report word count for substantive videos, count of blocked thin reports, and operator usefulness on a small manual sample.

## Stop conditions
- If focused tests fail, do not commit until the failure is understood and fixed within scope.
- If an untracked workspace artifact appears to be app-owned or runtime-critical, do not delete it.
- If cleanup requires runtime changes, stop and report before restarting services.
