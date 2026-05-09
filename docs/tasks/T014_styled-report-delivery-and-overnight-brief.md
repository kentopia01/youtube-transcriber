# T014 - Styled report delivery and overnight operations brief

## Status
Done

## Objective
Deliver completed YouTube transcriptions as styled, self-contained report artifacts through Telegram, and simplify the daily morning brief into an overnight operations/intelligence update that includes pending retries and failures.

## Why it matters
Ken wants the YouTube Transcriber Telegram bot to deliver finished intelligence directly, similar to the provided HTML report examples, instead of only sending short completion messages and redirecting back into chat/channel views.

## Scope
- Add a persistent report artifact model/storage path for generated per-video reports.
- Generate a styled HTML report for each completed video using existing transcript + summary data.
- Keep delivered HTML artifacts summary-only by default; transcripts remain available in the DB/app but are not included as an appendix.
- Send a simplified per-video Telegram completion message with the HTML report attached.
- Remove chat/channel redirect buttons from pushed report-completion messages by default.
- Preserve manual bot chat/channel capabilities; only simplify pushed delivery messages.
- Update the morning digest to summarize overnight activity, delivered reports, pending/queued/retrying jobs, failures/manual-review items, worker/system health, and LLM spend.
- Add focused tests for report rendering, artifact creation, Telegram document delivery, simplified completion rendering, and morning digest pending/retry status.

## Out of scope
- PDF export. HTML is the MVP artifact format.
- Major UI redesign of the web app.
- Changes to transcription, diarization, cleanup, embedding, queue routing, or retry semantics except where data is read for reporting.
- Public/external hosting of report files.
- Removing manual chat/channel commands from the Telegram bot.

## Constraints
- Keep the core pipeline resilient: report generation/delivery failures must not mark transcription as failed if transcript/summary/embed completed.
- Preserve existing completion behavior as fallback when report generation or document delivery is disabled/unavailable.
- Avoid hard-coding Ken-specific paths beyond existing config defaults.
- Use structured render data and templates rather than asking the LLM to emit arbitrary final HTML.
- Keep report CSS self-contained so Telegram document attachments render standalone.
- Respect existing cost tracking/budget guardrails for new LLM calls.
- Do not overwrite unrelated current work in `app/routers/subscriptions.py` or `tests/test_subscriptions_api.py`.

## Done criteria
- A completed video can produce a persisted summary-only HTML report artifact from DB summary data, with transcript data retained outside the artifact.
- The Telegram completion push for report-enabled videos sends a concise message plus attached `.html` report, with no Chat/Channel buttons.
- The daily morning digest includes overnight completed count, pending/queued/retrying count, failed/manual-review items, worker/system health summary, and LLM spend.
- Existing Telegram chat/channel bot commands still work unchanged.
- Focused tests pass for new report and notification behavior.
- Existing relevant tests pass: `tests/test_telegram_notify.py`, `tests/test_morning_digest.py`, and any new T014 tests.
- Migration/runtime steps are documented before rollout.

## Validation
- T014A report artifact MVP complete and focused tests pass.
- T014B Telegram document delivery complete and focused tests pass.
- T014C overnight brief operations status complete and focused tests pass.
- Relevant local validation passed: `tests/test_reporting.py`, `tests/test_telegram_notify.py`, `tests/test_embed_report_notification.py`, and `tests/test_morning_digest.py`.
- T014D summary-only report format complete: source callout moved to top and transcript appendix removed by default.
- T014E cleanup complete: redundant transcript report plumbing removed, report type renamed to `summary_report`, failed-send dedupe fixed, and a real Telegram `sendDocument` delivery-path test to Ken returned success.
- Runtime rollout validation completed: DB upgraded to Alembic `017`, web served HTTP 200, worker health passed, and an automatic-path smoke video produced a report artifact with delivery status `sent`.

## Notes
- Source examples: the two HTML reports Ken attached on 2026-05-09.
- Product direction: Telegram should behave as the finished-report delivery surface, not a prompt to navigate back into the app.
- Link to `docs/PLAN.md` and `docs/CLARIFICATIONS.md` for repo execution doctrine.
