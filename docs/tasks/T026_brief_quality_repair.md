# T026 - Brief quality repair and report depth gate

## Status
Done

## Objective
Repair the per-video brief pipeline so completed reports do not degrade into a single teaser paragraph for substantive videos. Future summaries should be generated from a structured contract and rendered as useful operator briefs with summary, takeaways, evidence, caveats, implications, and watch guidance.

## Scope
- Update the summary prompt to require structured JSON first.
- Normalize structured JSON into the markdown stored in `summaries`.
- Require the delivered brief sections:
  - At-a-Glance
  - Executive Summary
  - Key Takeaways
  - Detailed Brief
  - Notable Concepts & Terms
  - Operator Notes / Why Ken Should Care
  - Watch Map
  - Source/Metadata
- Add deterministic quality gates so long/substantive videos, including videos over 10 minutes or transcripts around 1,500+ words, cannot ship as a single-paragraph report.
- Regenerate a bounded batch of recent thin report artifacts after the renderer fix.

## Out of scope
- Queue topology, retry policy redesign, worker concurrency, Telegram UX redesign, PDF export, and unrelated template polish.
- Bulk backfill of all historical videos.

## Implementation notes
- Summary generation now asks Claude for a structured JSON brief, then converts valid JSON into markdown for existing storage/report paths.
- The summarize task runs a bounded quality-gate regeneration once before writing a malformed summary.
- Report generation blocks long/substantive report artifacts when the existing summary is too thin, while still allowing older useful T015-style summaries to render.
- The report template now exposes the full brief shape instead of only the 30-second scan.

## Verification
- PASS: `.venv/bin/python -m pytest tests/test_reporting.py tests/test_summary_quality.py tests/test_summarization_prompt.py tests/test_scan_first_backfill_script.py tests/test_scan_first_eval_script.py tests/test_telegram_notify.py tests/test_embed_report_notification.py -q` -> `62 passed`.

## Runtime evidence
- Regenerated a bounded recent batch of report artifacts after implementation; see final handoff for exact paths and counts.
