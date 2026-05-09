# T014D - Summary-only report format

## Status
Done

## Objective
Refine the delivered HTML report artifact so it is fast to scan and useful for follow-up: summary-first, no transcript appendix by default, and the source video shown as a top callout instead of a lower section.

## Scope
- Change default report artifact behavior to summary-only (`report_include_full_transcript=false`).
- Remove transcript appendix rendering from delivered HTML reports by default.
- Move source video link into a distinct top callout.
- Keep transcript data available in the DB/app; do not change transcription or storage semantics.
- Update focused reporting tests.
- Regenerate/smoke-check one report artifact.

## Out of scope
- Changing transcription, summarization, diarization, queue, retry, or Telegram command semantics.
- New LLM report generation.
- PDF export.
- Web UI redesign.

## Done criteria
- Generated HTML has a top source callout.
- Generated HTML does not include transcript appendix content by default.
- Focused reporting tests pass.
- One runtime report artifact is regenerated and inspected.

## Validation
- `python3 -m py_compile app/config.py app/services/reporting.py` passed.
- `.venv314/bin/python -m pytest tests/test_reporting.py -q` passed: 4 passed.
- `.venv314/bin/python -m pytest tests/test_reporting.py tests/test_telegram_notify.py tests/test_embed_report_notification.py tests/test_morning_digest.py -q` passed: 33 passed.
- Runtime report regenerated for smoke video `6277eb16-d213-4e0f-91f7-1d78d2226a4c`; artifact exists, source callout appears before 30-second scan, no transcript appendix, and prior delivery status remained `sent`.
