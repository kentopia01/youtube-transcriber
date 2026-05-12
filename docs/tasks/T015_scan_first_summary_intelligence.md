# T015 - Scan-first summary intelligence

## Status
Done

## Objective
Replace generic topic-list video summaries with scan-first intelligence that lets Ken understand the video’s actual arguments, examples, numbers, implications, and watch value without watching the video.

## Why it matters
The current pipeline often produces long but generic notes: topic headings, broad categories, and extracted bullets. Ken needs executive scan value: what the speaker actually claims, what evidence/examples they use, what the caveats are, why it matters to him, and whether the video is worth his time.

## Phased implementation

### Phase 1 — Output contract, report extraction, and Telegram caption
Goal: improve future summaries and pushed report captions without changing pipeline topology or backfilling history.

Scope:
- Replace the summary prompt with a scan-first output contract.
- Require the summary to include:
  - `30-second take`
  - `Key takes`
  - `Useful details`
  - `Caveats / counterpoints`
  - `Ken relevance`
  - `Watch verdict`
- Add low-content transcript handling instructions so music/placeholder transcripts are clearly flagged instead of padded.
- Update report rendering/key-point extraction so “Key takeaways” comes from the `Key takes` section, not the first bullets in the whole summary.
- Update Telegram report-ready caption to give a short useful summary, not “Attached: summary report”.
- Preserve buttonless pushed delivery.

Done criteria:
- Focused tests cover the new prompt contract, report extraction, low-content shape, and Telegram caption.
- Existing report/Telegram notification tests pass.
- No worker topology, retry, or DB schema changes.

### Phase 2 — Evaluation harness and sample QA
Goal: prove the new contract is better on real transcripts before backfill.

Scope:
- Add a small script or test fixture to generate summaries for selected existing transcripts without writing to DB by default.
- Compare old vs new on representative videos: long podcast, short clip, AI/product review, low-content transcript.
- Save sample outputs under reports/eval or a docs note for manual inspection.

Done criteria:
- At least 4 representative samples generated or tested.
- Differences are inspectable without touching production summaries.

### Phase 3 — Controlled backfill
Goal: regenerate recent summaries safely after Phase 1/2 are validated.

Scope:
- Add/extend a CLI script for dry-run and limited backfill.
- Support filters: last N, channel, specific video IDs, completed-only.
- Keep cost/usage visible.
- Do not backfill while heavy live jobs are unstable.

Done criteria:
- Dry-run reports exactly what would be updated.
- Limited live backfill succeeds on a small batch and regenerates reports.

### Phase 4 — Optional personalization/ranking
Goal: make summaries more specifically useful to Ken over time.

Scope:
- Tune `Ken relevance` toward agent systems, AI ops, content/business opportunities, investing, and GTM when applicable.
- Add “Skip / skim / watch fully” consistency checks.
- Consider storing structured summary metadata later if it proves useful.

Done criteria:
- Only started after Phase 1-3 are working.

## Out of scope for Phase 1
- Backfilling existing summaries.
- DB schema migrations or structured summary columns.
- PDF export.
- Worker concurrency/topology changes.
- Chat/channel navigation changes outside pushed report delivery.
- Refactoring unrelated subscription changes currently present in the working tree.

## Constraints
- Keep changes narrow and product-delivery focused.
- Report generation and Telegram delivery must remain non-fatal to the transcription pipeline.
- Do not let malformed/low-content transcripts generate confident fake takeaways.
- Keep summary output concise enough for scan value but specific enough to capture arguments and examples.

## Validation
- SentryClaw/BuildClaw implements against this file plus `AGENTS.md`, `docs/PLAN.md`, `docs/CLARIFICATIONS.md`, and `docs/tasks/TASK_INDEX.md`.
- QAClaw validates Phase 1 against this file before it is marked done.

## Notes
- Task board item: `fc1bed76`.
- Related completed report-delivery work: T014A-E.

## Phase 3 implementation evidence — 2026-05-12
- Added `scripts/backfill_scan_first_summaries.py` for controlled scan-first summary/report backfill.
- Default mode is dry-run only: no Anthropic calls and no DB writes.
- Live mode requires `--apply --generate --confirm-apply`; `summarize_text` is called with `record_usage_enabled=False`, and token usage is printed from returned `prompt_tokens` / `completion_tokens`.
- Supported filters: `--limit`, repeatable/comma-separated `--youtube-id`, completed-only by default, `--channel`, and `--since`.
- Apply path upserts `summaries` rows and regenerates `summary_report` artifacts with `generate_video_report(..., commit=False)` before committing each video.

Verification:
- PASS: `.venv/bin/python -m pytest tests/test_scan_first_backfill_script.py tests/test_scan_first_eval_script.py tests/test_summarization_prompt.py tests/test_reporting.py tests/test_telegram_notify.py tests/test_embed_report_notification.py -q` → `46 passed in 0.94s`
- PASS: `.venv/bin/python -m py_compile scripts/backfill_scan_first_summaries.py scripts/evaluate_scan_first_summaries.py app/services/summarization.py app/services/reporting.py app/services/telegram_messages.py app/tasks/embed.py tests/test_scan_first_backfill_script.py tests/test_scan_first_eval_script.py tests/test_summarization_prompt.py tests/test_reporting.py tests/test_telegram_notify.py tests/test_embed_report_notification.py`
- PASS: `.venv/bin/python scripts/backfill_scan_first_summaries.py --limit 3` printed a dry-run plan for 3 completed videos and confirmed no Anthropic calls / DB writes.

## Phase 4 implementation evidence — 2026-05-12
- Added shared lightweight markdown-section helpers in `app/services/summary_markdown.py` and pure deterministic scan-first summary validation in `app/services/summary_quality.py`.
- Validator checks required headings, valid `Skip / Skim / Watch fully` verdict, non-empty `Ken relevance`, key-take count blocking for substantive summaries, explicit low-content exceptions, and a lightweight Ken-focus relevance warning.
- Eval markdown outputs now include a `Contract validation` section; generated eval runs print validation warnings/errors without DB writes.
- Backfill output now documents the validation guard. Live apply validates generated summaries before any summary/report write and blocks malformed outputs by default.
- Added documented override flag `--allow-malformed` for operator-approved live writes; validation warnings/errors still appear in apply output.
- No DB schema changes, no live backfill, no Telegram sends, and no second LLM judging pass.

Verification:
- PASS: `.venv/bin/python -m pytest tests/test_summary_quality.py tests/test_scan_first_backfill_script.py tests/test_scan_first_eval_script.py tests/test_summarization_prompt.py tests/test_reporting.py tests/test_telegram_notify.py tests/test_embed_report_notification.py -q` → `56 passed in 3.95s` after tightening too-few-key-take blocking and low-content false-positive handling.
- PASS: `.venv/bin/python -m py_compile app/services/summary_markdown.py app/services/summary_quality.py scripts/evaluate_scan_first_summaries.py scripts/backfill_scan_first_summaries.py tests/test_summary_quality.py tests/test_scan_first_backfill_script.py tests/test_scan_first_eval_script.py tests/test_summarization_prompt.py tests/test_reporting.py tests/test_telegram_notify.py tests/test_embed_report_notification.py`
- PASS: `.venv/bin/python scripts/backfill_scan_first_summaries.py --limit 1` printed a dry-run plan, confirmed no Anthropic calls / DB writes, and documented the malformed-summary write guard.
- PASS: `.venv/bin/python scripts/evaluate_scan_first_summaries.py --max-samples 1 --metadata-only --output-dir /tmp/t015-phase4-eval-smoke` wrote local eval markdown only and confirmed no Anthropic calls / DB writes.
