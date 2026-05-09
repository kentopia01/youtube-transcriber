# T014C - Overnight brief operations status

## Status
Done

## Objective
Upgrade the morning digest into an overnight intelligence and operations brief that includes completed reports, queued/pending/retrying work, failures/manual-review items, worker/system health, and LLM spend.

## Scope
- Extend digest input gathering with queued/pending/retrying pipeline jobs.
- Include failed/manual-review items and retry context from existing job recovery fields.
- Include lightweight health/spend ledger from existing DB/service signals.
- Update digest prompt/output to emphasize overnight status instead of chat/channel navigation.
- Add focused tests for prompt block and Telegram digest rendering.

## Out of scope
- Per-video report generation/delivery.
- New worker topology or recovery semantics.
- Web UI redesign.

## Constraints
- Read existing state only; do not alter retry/queue behavior.
- Keep digest concise enough for Telegram.
- Avoid navigation/button nudges.

## Done criteria
- Morning digest input block includes completed count, pending/retrying count, failures/manual-review, health summary, and LLM spend.
- Digest renderer remains Telegram-safe.
- Focused morning digest tests pass.

## Validation
- Started after T014A and T014B were marked done.
- `python3 -m py_compile app/services/digest.py app/tasks/morning_digest.py` passed.
- `.venv314/bin/python -m pytest tests/test_morning_digest.py -q` passed: 8 passed.
- `.venv314/bin/python -m pytest tests/test_morning_digest.py tests/test_reporting.py tests/test_telegram_notify.py tests/test_embed_report_notification.py -q` passed: 32 passed.
- `.venv314/bin/alembic heads` reports `017 (head)`.
- `.venv314/bin/alembic current` could not connect from host because configured DB host `postgres` is not resolvable outside the service network; no migration state change was attempted.
