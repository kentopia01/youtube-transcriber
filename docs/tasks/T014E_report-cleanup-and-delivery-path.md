# T014E - Report cleanup and delivery path validation

## Status
Done

## Objective
Clean up the just-landed T014 report delivery implementation now that delivered HTML reports are summary-only, and validate the real Telegram document delivery path to Ken through the youtube-transcriber bot.

## Scope
- Remove now-redundant transcript appendix/report rendering plumbing from report generation.
- Remove the `report_include_full_transcript` setting.
- Stop querying `TranscriptionSegment` during report generation.
- Allow report rendering/generation to work from `Video` + `Summary` without requiring a transcription; transcription is only used opportunistically for word count.
- Rename stale report type naming from `summary_transcript` to `summary_report` in code defaults and generated reports.
- Improve Telegram notification dedupe so failed sends do not reserve the dedupe window.
- Validate a real `video.report_ready` document send to the allowlisted Telegram user via the app's own settings/environment.

## Out of scope
- Transcription, diarization, queue, retry, and subscription semantics.
- Report visual redesign beyond removing dead transcript plumbing.
- Remote push.
- Unrelated dirty subscription files.

## Implementation notes
- `video_reports.report_type` has no Alembic/server default in revision `017`, so no DB migration was needed for the Python-side default rename.
- Existing rows with the old report type are updated on regeneration; the runtime validation regenerated the smoke report as `summary_report`.
- Telegram dedupe now reserves in-flight events and commits dedupe only after a successful send; failed sends roll back the reservation and can be retried immediately.

## Validation
- `python3 -m py_compile app/config.py app/models/video_report.py app/services/reporting.py app/services/telegram_notify.py` passed.
- `.venv314/bin/python -m pytest tests/test_reporting.py tests/test_telegram_notify.py -q` passed: 24 passed.
- `.venv314/bin/python -m pytest tests/test_reporting.py tests/test_telegram_notify.py tests/test_embed_report_notification.py tests/test_morning_digest.py -q` passed: 35 passed.
- `.venv314/bin/python -m pytest -q` passed: 1084 passed, 10032 warnings.
- Runtime Telegram delivery path test passed using `.env.native` and `video.report_ready` through `app.services.telegram_notify`:
  - explicit test send: yes (`[T014E delivery path test]` caption prefix)
  - allowed user/chat: `5815973193`
  - video: `6277eb16-d213-4e0f-91f7-1d78d2226a4c` / `Keyboard Cat! - THE ORIGINAL!`
  - report id: `7e20c463-517b-490b-afc4-2c9248cbae3d`
  - report type: `summary_report`
  - delivery status: `sent`
  - delivery error: `null`
  - artifact path: `/Users/sentryclaw/Projects/youtube-transcriber/data/reports/2026-05-09/6277eb16-d213-4e0f-91f7-1d78d2226a4c/keyboard-cat-the-original_report.html`
  - artifact exists: yes
  - `sendDocument` called: yes
  - `sendDocument` returned success: yes
  - filename: `keyboard-cat-the-original_report.html`
  - mime type: `text/html`
- `git diff --check` passed.

## Result
T014E cleanup is complete and the real Telegram document delivery path to Ken has been validated without using the OpenClaw message tool.
