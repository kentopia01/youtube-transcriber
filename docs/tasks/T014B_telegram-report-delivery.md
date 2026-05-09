# T014B - Telegram report document delivery

## Status
Done

## Objective
Deliver generated per-video HTML reports through Telegram as document attachments with concise completion messages and no Chat/Channel buttons by default.

## Scope
- Add Telegram `sendDocument` support to the source-agnostic notifier.
- Add a `video.report_ready` renderer/event with concise text and document path metadata.
- Integrate report generation/delivery after completion as non-fatal post-processing.
- Preserve existing `video.completed` as fallback when report generation or delivery is disabled/unavailable.
- Add tests for document payload, no-button completion behavior, dedupe, and fallback.

## Out of scope
- Morning digest changes.
- PDF export.
- Removing manual chat/channel bot commands.
- Public report hosting.

## Constraints
- Report delivery failures must not fail the completed transcription pipeline.
- Do not include Chat/Channel redirect buttons in pushed report-ready messages by default.
- Keep manual bot commands unchanged.

## Done criteria
- A generated report can be sent via Telegram document attachment.
- Pushed report-ready message is concise and buttonless by default.
- Existing completion fallback still works when report delivery is off or fails.
- Focused Telegram notification tests pass.

## Validation
- Started after T014A was marked done.
- `python3 -m py_compile app/services/telegram_messages.py app/services/telegram_notify.py app/tasks/embed.py` passed.
- `.venv314/bin/python -m pytest tests/test_reporting.py tests/test_telegram_notify.py tests/test_embed_report_notification.py -q` passed: 24 passed.
- `.venv314/bin/python -m pytest tests/test_morning_digest.py tests/test_telegram_notify.py tests/test_embed_report_notification.py -q` passed: 28 passed.
