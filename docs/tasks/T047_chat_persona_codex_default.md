# T047 - Chat and persona Codex default

## Status
Done

## Objective
Move web/Telegram chat, direct video Q&A, and channel persona generation/refresh onto the local Smart Router Codex route by default, while keeping Anthropic as the explicit fallback and rollback path.

## Scope
- Change chat defaults to:
  - `CHAT_LLM_PROVIDER=openai_compatible`
  - `CHAT_MODEL=codex`
  - `CHAT_LLM_BASE_URL=http://127.0.0.1:8400/v1`
  - `CHAT_LLM_FALLBACK_PROVIDER=anthropic`
  - `CHAT_LLM_FALLBACK_MODEL=claude-haiku-4-5`
- Change persona defaults to:
  - `PERSONA_LLM_PROVIDER=openai_compatible`
  - `PERSONA_MODEL=codex`
  - `PERSONA_LLM_BASE_URL=http://127.0.0.1:8400/v1`
  - `PERSONA_LLM_FALLBACK_PROVIDER=anthropic`
  - `PERSONA_LLM_FALLBACK_MODEL=claude-sonnet-4-5`
- Keep Anthropic reachable by setting `CHAT_LLM_PROVIDER=anthropic` or `PERSONA_LLM_PROVIDER=anthropic`.
- Ensure Telegram `/ask_video` follows the same chat provider path.

## Out of scope
- Transcript cleanup, which remains Anthropic Haiku when enabled.
- Queue topology, transcription, diarization, embeddings, or report rendering changes.
- Storing or reading Codex OAuth tokens in the transcriber.

## Done criteria
- Chat and persona provider defaults are Codex-primary with Anthropic fallback.
- Existing Anthropic fallback remains tested and reachable.
- Focused chat/persona/config tests pass.
- Live non-mutating smokes through Smart Router prove chat and persona calls return Codex-routed models.

## Validation
- PASS: Smart Router `/health` and `/v1/models` reachable with `codex`.
- PASS: Focused config, chat, persona, and provider tests passed.
- PASS: Live non-mutating chat smoke returned a Codex-routed model.
- PASS: Live non-mutating persona derivation smoke returned a Codex-routed model.
