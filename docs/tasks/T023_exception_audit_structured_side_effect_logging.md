# T023 - Broad exception audit and structured side-effect logging

## Status
Done — implementation and QA validation passed.

## Objective
Audit broad exception handlers at side-effect boundaries and add structured logs/classification without breaking intentional fail-open behavior.

## Why it matters
T016 found many `except Exception` handlers across Telegram, services, tasks, routers, and scripts. Some are correct fail-open boundaries, especially notifications/report delivery. Others risk hiding real regressions through silent pass, generic HTTP errors, or unstructured logs.

## Source of truth
Read in order:
1. `AGENTS.md`
2. `docs/PLAN.md`
3. `docs/CLARIFICATIONS.md`
4. `docs/tasks/TASK_INDEX.md`
5. `docs/tasks/T016_full_project_engineering_audit.md`
6. this file

## In scope
Keep this slice narrow and high-value:
- Audit and classify broad catches in the highest-risk side-effect boundaries:
  - `app/tasks/embed.py` report generation/delivery fail-open path
  - `app/services/telegram_notify.py` best-effort Telegram send/document/dedupe path
  - `app/tasks/morning_digest.py` and `app/tasks/weekly_digest.py` notification fail-open path
  - `app/tasks/generate_persona.py` persona notification/enqueue fail-open path
  - `app/services/pipeline_recovery.py` notifier fail-open path
  - existing T022 next-batch enqueue failure logging if useful
- Add/standardize structured log fields for fail-open side effects:
  - event name
  - boundary/category, e.g. `best_effort_side_effect`, `expected_external_failure`, `bug_mask_candidate`
  - entity IDs where safe (`video_id`, `job_id`, `channel_id`, `batch_id`, `event_type`, report path)
  - exception type and message
  - operator-visible outcome (`suppressed`, `fallback_sent`, `caller_continued`, `marked_failed`)
- Add tests that prove failures remain fail-open but are visible in structured logs.
- Document audited catch classifications in this task file.

## Out of scope
- Do not remove fail-open behavior blindly.
- Do not attempt to classify/fix every broad catch in the repository.
- Do not change user-facing Telegram/report behavior except adding logs.
- Do not run live Telegram, LLM, Celery, Redis, or DB mutation flows.
- Do not refactor unrelated pipeline logic.
- Do not clean up the broad dirty tree.

## Known starting points
- `app/tasks/embed.py`
- `app/services/telegram_notify.py`
- `app/tasks/morning_digest.py`
- `app/tasks/weekly_digest.py`
- `app/tasks/generate_persona.py`
- `app/services/pipeline_recovery.py`
- `tests/test_embed_report_notification.py`
- `tests/test_telegram_notify.py`
- `tests/test_morning_digest.py`
- `tests/test_weekly_digest.py`
- persona task tests

## Required behavior
- Best-effort side effects still must not fail the caller/pipeline.
- Every audited fail-open catch should emit a structured log with enough context to diagnose later.
- Logs must not include secrets, API keys, full transcript text, or private message bodies.
- Tests should capture log calls by monkeypatching module loggers or using existing logging test helpers; no live external calls.
- If a catch is a likely bug mask but not safe to change now, classify it in the task doc and leave a targeted follow-up note rather than changing behavior broadly.

## Required validation
Use safe commands only:

```bash
.venv/bin/python -m pytest tests/test_embed_report_notification.py tests/test_telegram_notify.py tests/test_morning_digest.py tests/test_weekly_digest.py -q
.venv/bin/python -m pytest <persona/pipeline recovery focused tests> -q
.venv/bin/python -m compileall -q app/tasks/embed.py app/services/telegram_notify.py app/tasks/morning_digest.py app/tasks/weekly_digest.py app/tasks/generate_persona.py app/services/pipeline_recovery.py
.venv/bin/python -m pytest --collect-only -q
git diff --check -- <T023 touched files>
```

If a target module has no focused tests, add narrow tests or document why it was audited without code change.

## Acceptance criteria
- High-risk side-effect broad catches are audited and classified.
- Structured logging is added or verified for each audited fail-open boundary.
- Fail-open behavior remains intact and tested.
- No live external/runtime mutations occur.
- Safe validation passes.
- QA validates before T023 is marked done.

## Audited catch classifications

| Boundary | Classification | Structured log event(s) | Fail-open outcome | Notes |
|---|---|---|---|---|
| `app/tasks/embed.py` report generation / report-ready delivery | `best_effort_side_effect` | `video_report_delivery_failed`, `video_report_side_effect_failed` | `fallback_sent` | Report failures keep the completed pipeline job successful and fall back to `video.completed`. Logs include `video_id`, `channel_id`, `event_type`, `report_path`, exception type/message or notify-false reason. |
| `app/tasks/embed.py` report failure-state update and completion notification safety nets | `bug_mask_candidate`, `best_effort_side_effect` | `video_report_failure_state_update_failed`, `video_completion_notification_failed`, `video_completion_side_effect_failed` | `caller_continued` | DB/report-state update and final notification failures are visible but still suppressed so completion is not poisoned. Follow-up should narrow DB catches if a safe DB error taxonomy is introduced. |
| `app/services/telegram_notify.py` state load / sendMessage / sendDocument / document missing / renderer / dedupe / absolute safety net | `best_effort_side_effect`, `expected_external_failure`, `bug_mask_candidate` | `telegram_notify_state_load_failed`, `telegram_notify_send_failed`, `telegram_notify_document_missing`, `telegram_notify_document_send_failed`, `telegram_notify_render_failed`, `telegram_notify_deduped`, `telegram_notify_dedupe_finish_failed`, `telegram_notify_failed` | `suppressed`, `settings_fallback_used`, `caller_continued` | Fire-and-forget semantics preserved. Logs include safe entity context (`video_id`, `job_id`, `channel_id`, `batch_id`, `report_path`), `event_type`, `dedupe_key`, exception type/message, status code where applicable. No token, message body, or Telegram URL is logged. |
| `app/tasks/morning_digest.py` Telegram notification | `expected_external_failure`, `best_effort_side_effect` | `morning_digest_notify_not_sent`, `morning_digest_notify_failed` | `caller_continued` | Digest generation result is returned even when push delivery is false/raises. |
| `app/tasks/weekly_digest.py` Telegram notification | `expected_external_failure`, `best_effort_side_effect` | `weekly_digest_notify_not_sent`, `weekly_digest_notify_failed` | `caller_continued` | Weekly stats result is returned even when push delivery is false/raises. |
| `app/tasks/generate_persona.py` persona notification | `expected_external_failure`, `best_effort_side_effect` | `channel_persona_notify_not_sent`, `channel_persona_notify_failed` | `caller_continued` | Persona generation stays successful when notification fails. Logs include `channel_id`, `persona_id`, and event type. |
| `app/tasks/generate_persona.py` persona enqueue wrapper | `best_effort_side_effect` | `channel_persona_enqueue_failed` | `caller_continued` | Upstream embed completion is not failed by persona enqueue broker errors; log includes `channel_id` and `forced`. |
| `app/services/pipeline_recovery.py` failure notifier | `expected_external_failure`, `best_effort_side_effect` | `pipeline_failure_notify_not_sent`, `pipeline_failure_notify_failed` | `caller_continued` | Pipeline failure state remains authoritative even if the `video.failed` Telegram side effect fails. Logs include `job_id`, `video_id`, `stage`, and event type. |
| `app/services/channel_dispatcher.py` T022 next-batch enqueue continuation | `best_effort_side_effect` | `channel_batch_advance_enqueue_failed` | `caller_continued` | A next-batch enqueue failure stays local to the next job and does not poison the just-completed current pipeline job. Logs include source/next batch IDs and next job ID. |
| `app/services/channel_dispatcher.py` next-batch progress refresh commit catch | `bug_mask_candidate` | `channel_batch_advance_progress_commit_failed` | `caller_continued` | Commit failure is now visible but still suppressed to preserve the T022 fail-open boundary. Follow-up should narrow once DB taxonomy exists. |

## Verification evidence

Safe local validation only; no live Telegram, LLM, Celery, Redis, or DB mutation flows were run.

```bash
.venv/bin/python -m pytest tests/test_embed_report_notification.py tests/test_telegram_notify.py tests/test_morning_digest.py tests/test_weekly_digest.py -q
# 37 passed in 0.37s

.venv/bin/python -m pytest tests/test_persona_task_and_trigger.py tests/test_pipeline_recovery.py tests/test_channel_dispatcher.py -q
# 27 passed in 0.51s

.venv/bin/python -m compileall -q app/tasks/embed.py app/services/telegram_notify.py app/tasks/morning_digest.py app/tasks/weekly_digest.py app/tasks/generate_persona.py app/services/pipeline_recovery.py app/services/channel_dispatcher.py
# passed (no output)

.venv/bin/python -m pytest --collect-only -q
# 1167 tests collected in 0.56s
```

```bash
git diff --check -- app/tasks/embed.py app/services/telegram_notify.py app/tasks/morning_digest.py app/tasks/weekly_digest.py app/tasks/generate_persona.py app/services/pipeline_recovery.py app/services/channel_dispatcher.py tests/test_embed_report_notification.py tests/test_telegram_notify.py tests/test_morning_digest.py tests/test_weekly_digest.py tests/test_persona_task_and_trigger.py tests/test_pipeline_recovery.py tests/test_channel_dispatcher.py
# passed (no output)

git diff --check --no-index -- /dev/null docs/tasks/T023_exception_audit_structured_side_effect_logging.md
# whitespace-check passed for untracked T023 doc (no whitespace output; no-index diff status ignored)
```

## QA evidence

- PASS: QA repeated focused notification/digest tests: `37 passed`.
- PASS: QA repeated persona/recovery/dispatcher tests: `27 passed`.
- PASS: QA repeated task orchestration regression: `6 passed`.
- PASS: QA verified compileall, collect-only `1167 collected`, diff-check, and untracked doc whitespace/final-newline checks.
- PASS: QA verified fail-open behavior was preserved and logs use safe context only; no bot tokens, API keys, full transcripts, or private message bodies found in audited logs.
