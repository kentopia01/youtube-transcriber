# T050 - Codex workload router profiles

## Status
Done

## Objective
Keep YouTube Transcriber LLM workloads on the local Codex/OAuth Smart Router path while routing each workload to a more appropriate Codex model tier instead of using the generic `codex` profile everywhere.

## Scope
- Add Smart Router workload profile names for YouTube paths:
  - `yt-cleanup`
  - `yt-caption`
  - `yt-summary`
  - `yt-digest`
  - `yt-chat`
  - `yt-persona`
  - `yt-repair`
- Change YouTube Transcriber defaults and env examples to use the workload profile names.
- Keep the existing local OpenAI-compatible Smart Router boundary at `http://127.0.0.1:8400/v1`.
- Keep Anthropic fallback settings intact as emergency rollback.

## Out of scope
- Adding GLM, Kimi, or other API-key providers.
- Changing transcription, diarization, embeddings, queue topology, report rendering, or recipient lanes.
- Copying or reading Codex OAuth tokens in YouTube Transcriber.
- Implementing new quality-gate repair loops beyond the existing summary validation behavior.

## Acceptance criteria
- Smart Router exposes the new `yt-*` profiles via `/v1/models`.
- Smart Router accepts `yt-summary` and `smart-router/yt-summary` model names as routing profiles.
- YouTube Transcriber defaults are:
  - `CLEANUP_MODEL=yt-cleanup`
  - `SUMMARY_MODEL=yt-summary`
  - `CHAT_MODEL=yt-chat`
  - `PERSONA_MODEL=yt-persona`
  - `DIGEST_MODEL=yt-digest`
- Runtime `.env` / `.env.native` cleanup settings use `yt-cleanup`.
- Focused Smart Router and YouTube Transcriber tests pass.
- Smart Router is restarted and live model metadata confirms the new profiles.

## Validation
- Smart Router build and full test suite passed: 116 tests.
- YouTube Transcriber full test suite passed: 1,213 passed, 12 skipped.
- Smart Router smoke coverage verifies both `yt-summary` and `smart-router/yt-summary` route through the workload profile.
- Live `http://127.0.0.1:8400/v1/models` metadata confirmed all seven `yt-*` profiles after the launch agent restart.
- Runtime `.env.native` and `.env.example` use the workload-specific defaults, including `CLEANUP_MODEL=yt-cleanup`.
- `git diff --check` passed in both repositories.
