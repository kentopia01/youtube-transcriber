# T014A - Report artifact MVP

## Status
Done

## Objective
Generate and persist a self-contained styled HTML report artifact for a completed video using existing transcript and summary data.

## Why it matters
This creates the reliable artifact foundation before Telegram document delivery or morning brief changes are added.

## Scope
- Add/verify `video_reports` persistence model and migration.
- Add report configuration for artifact generation and storage path.
- Add deterministic report rendering service from `Video`, `Summary`, `Transcription`, and `TranscriptionSegment` data.
- Add a self-contained HTML template styled similarly to Ken's sample reports.
- Include transcript appendix when enabled.
- Add focused tests for report render data, HTML rendering, artifact file creation, and upsert behavior.

## Out of scope
- Telegram delivery / `sendDocument`.
- Completion notification changes.
- Morning digest changes.
- PDF export.
- New LLM report-generation prompts.
- Web UI changes.

## Constraints
- Do not alter transcription, diarization, cleanup, summarize, embed, retry, or queue semantics.
- Keep report generation deterministic from already-stored DB data for MVP.
- Keep CSS self-contained in the HTML artifact.
- Do not touch unrelated dirty subscription files.

## Done criteria
- A completed video with transcript + optional summary can generate a persisted `.html` report under the configured artifact directory.
- `video_reports` row is inserted/updated with artifact path and HTML content.
- Generated HTML contains the video title, executive summary, key points when available, and transcript appendix.
- Focused report tests pass.
- `python3 -m py_compile app/services/reporting.py app/models/video_report.py` passes.

## Validation
- `python3 -m py_compile alembic/versions/017_add_video_reports.py app/services/reporting.py app/models/video_report.py` passed.
- `.venv314/bin/python -m pytest tests/test_reporting.py -q` passed: 3 passed.
- `.venv314/bin/alembic heads` passed: `017 (head)`.
- Broader template safety check passed with reporting tests: `.venv314/bin/python -m pytest tests/test_reporting.py tests/test_template_rendering.py -q` → 71 passed.
