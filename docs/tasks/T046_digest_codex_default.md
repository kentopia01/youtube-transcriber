# T046 - Digest Codex default

## Status
Done

## Objective
Switch morning/daily digest generation to the local Smart Router Codex route by default, with Anthropic as fallback.

## Why it matters
Digest is part of the unattended YouTube intelligence path Ken actually reads. Leaving it on a different primary model after summary promotion creates split behavior across the overnight workflow.

## Scope
- Change digest defaults to:
  - `DIGEST_LLM_PROVIDER=openai_compatible`
  - `DIGEST_MODEL=codex`
  - `DIGEST_LLM_BASE_URL=http://127.0.0.1:8400/v1`
  - `DIGEST_LLM_FALLBACK_PROVIDER=anthropic`
  - `DIGEST_LLM_FALLBACK_MODEL=claude-sonnet-4-5`
- Keep Anthropic reachable by setting `DIGEST_LLM_PROVIDER=anthropic`.
- Update config tests and operator docs to match the promoted default.

## Out of scope
- Changing cleanup, chat, persona, transcription, diarization, embeddings, queue topology, global search, or report rendering.
- Sending a live digest notification during validation.
- Storing or reading Codex OAuth tokens in the transcriber.

## Constraints
- Validate Smart Router health and run a non-delivering digest call through Codex before claiming the default is safe.
- Keep digest fallback explicit and Anthropic-based.

## Done criteria
- Digest provider defaults are Codex-primary with Anthropic fallback.
- Existing env overrides can still force Anthropic.
- Focused config/digest tests pass.
- Fresh non-delivering digest eval uses a Codex model and does not send Telegram output.

## Validation
- PASS: Smart Router `/health` and `/v1/models` reachable.
- PASS: Direct `model=codex` Smart Router smoke returned `gpt-5.6-terra`.
- PASS: Fresh non-delivering 24h digest eval with fallback disabled returned `gpt-5.6-sol`, processed 3 completed videos and 1 failed item, had 0 pending/retrying/manual-review jobs, and produced a digest containing `**Opener**`.
