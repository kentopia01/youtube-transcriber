# T045 - Summary delivery polish and Codex default

## Status
Done

## Objective
Make per-video summaries useful in the first Telegram surface, remove the Watch Map section, reduce remaining full-report repetition, and switch the summary workload to Codex primary with Anthropic fallback.

## Scope
- Add a compact Telegram-first decision brief for `video.report_ready` captions.
- Keep the full HTML/markdown report as the attached appendix.
- Remove the Watch Map section from the summary contract, quality validator, HTML report, markdown report, and tests.
- Tighten Detailed Brief behavior so it acts as extra detail rather than a second pass over Key Takeaways.
- Change summary defaults to use the local Smart Router Codex route:
  - `SUMMARY_LLM_PROVIDER=openai_compatible`
  - `SUMMARY_MODEL=codex`
  - `SUMMARY_LLM_BASE_URL=http://127.0.0.1:8400/v1`
  - `SUMMARY_LLM_FALLBACK_PROVIDER=anthropic`
  - `SUMMARY_LLM_FALLBACK_MODEL=claude-sonnet-4-5`
- Keep Anthropic available as the explicit rollback path.

## Out of scope
- Switching digest defaults before digest-specific evaluation.
- Changing transcription, diarization, embeddings, queue topology, search, or chat behavior.
- Storing or reading Codex OAuth tokens in the transcriber.
- Adding a timestamp reconstruction system in this chunk, because Watch Map is being removed.

## Acceptance criteria
- Generated summaries no longer require or render `## Watch Map`.
- Report HTML and markdown do not include a Watch Map section.
- Telegram report-ready captions are concise and action-oriented, not a dump of the full report.
- Summary provider defaults are Codex-primary with Anthropic fallback.
- Existing Anthropic summary path remains reachable by setting `SUMMARY_LLM_PROVIDER=anthropic`.
- Focused tests pass for summarization prompt/normalization, quality validation, report rendering/captions, Telegram notify, provider config, and eval/backfill boundaries.
- A non-mutating five-video dry run validates the new contract and confirms production DB writes remain off.

## Validation log
- PASS: Focused summary/report/provider tests: `.venv/bin/python -m pytest tests/test_summarization_prompt.py tests/test_summary_quality.py tests/test_reporting.py tests/test_telegram_notify.py tests/test_embed_report_notification.py tests/test_config.py tests/test_model_config_paths.py tests/test_scan_first_backfill_script.py tests/test_scan_first_eval_script.py` -> `112 passed`.
- PASS: `git diff --check`.
- PASS: Smart Router health at `http://127.0.0.1:8400/health`.
- PASS: Non-mutating five-video Codex-primary dry run wrote local artifacts under `reports/eval/codex-primary-smoke-20260714-t045`; production `summaries` rows were not updated.
- PASS: Dry run used Smart Router Codex route (`gpt-5.6-sol`) for all five outputs and all five passed the deterministic structured-summary contract.
- PASS: `rg "## Watch Map|watch_map|timestamp unavailable:" reports/eval/codex-primary-smoke-20260714-t045` returned no matches.
