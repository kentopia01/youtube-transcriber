# T080 - Summary-first Tailnet and mobile Reader fixes

## Status

Done

## Objective

Make the shipped Reader match the primary scan-first workflow and make that
workflow fully usable through the existing tailnet-only Tailscale Serve route.

## In scope

- Render the persisted summary as the default content on `/read/{video_id}`.
- Keep the full timestamped transcript available as an explicit deeper-reading
  disclosure, with an explicit resume path for saved transcript progress.
- Preserve the transcript-only fallback when a readable video has no summary.
- Accept browser same-origin mutations when HTTPS is terminated by the trusted
  local reverse proxy while continuing to reject genuinely cross-site requests.
- Remove the observed 768px Library filter overflow.
- Repair observed mobile/tablet touch targets in Reader and Chat navigation.
- Stop labeling RRF fusion scores as user-facing semantic similarity
  percentages in Ask source cards.

## Out of scope

- Changing chat-session ownership or retrieval-scope persistence.
- Changing embedding models, schemas, chunking, ranking, or backfilling data.
- Adding public internet access, Tailscale Funnel, or a second deployment.
- Redesigning Operations.

## Guardrails

- Existing summaries and transcripts remain the source content; opening Reader
  must not invoke an LLM.
- Transcript timestamps, progress, annotations, search, and appearance controls
  remain available.
- Tailscale support must preserve the loopback listener and fail-closed
  cross-site browser boundary.
- No embedding or pipeline data mutation is part of this chunk.

## Validation

- Focused Reader, workspace, security, rendering, and browser contract tests.
- Live desktop, tablet, and mobile screenshots for Reader Home, Library,
  summary-first document, Highlights, Search, and Ask.
- Live browser Search/Ask POST checks through the tailnet HTTPS URL.
- Default HTTP and browser feature-area gates remain green.

## Completion evidence

- Reader documents now render the persisted summary first and keep the full
  transcript in an explicit disclosure. Saved transcript progress has a direct
  resume link, while summary-less documents retain the transcript fallback.
- Tailscale Serve HTTPS mutations pass the same-host origin boundary via
  `X-Forwarded-Proto`; cross-site requests remain blocked.
- The 768px Library overflow, tablet pagination targets, mobile Reader links,
  mobile Chat targets, and the clipped mobile Ask composer were repaired.
- Ask source cards identify Summary versus Transcript instead of presenting RRF
  fusion scores as semantic-match percentages.
- Repository suite: `1382 passed, 11 skipped`.
- Live HTTP feature gate: `33/33 passed`.
- Live Chromium gate through Tailscale HTTPS: `30/30 passed`.
- Post-fix visual audit covered Reader Home, Library, document, Highlights,
  Search, and Ask at 1440x900, 768x1024, and 390x844.

Review findings and the proposed Ask/embedding follow-on are recorded in
`docs/evaluations/T080_reader_ask_embedding_review_2026-07-31.md`.
