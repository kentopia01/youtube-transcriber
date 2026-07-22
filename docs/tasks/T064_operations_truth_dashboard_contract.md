# T064 - Operations Truth and Dashboard Contract

## Status

Done

## Objective

Make Operations dashboard state structured, accurate, and actionable before
redesigning its presentation.

## Why it matters

The current UI includes a hardcoded queue-health badge, an active-job count based
on a limited result set, stale active batches, inconsistent channel counts, and
hidden report-delivery problems. An operations product cannot build trust on
misleading aggregates.

## Scope

- Define a dashboard/health aggregate service or schema.
- Reconcile or explicitly classify stale batch state.
- Return true active, pending, failed-visible, and recent-completion counts.
- Expose worker/queue coverage with busy-vs-unhealthy semantics.
- Expose report-delivery and subscription warning counts.
- Correct channel/video count drift through a structured source of truth.
- Add focused service, route, and rendering tests before UI changes.
- Replace stale runtime/product copy with actual configured capabilities.

## Out of scope

- Reader UI or reading-state implementation.
- Broad visual redesign.
- Queue concurrency or routing changes.
- Retrying historical T061 jobs.
- Bulk report resend or subscription mutation.

## Constraints

- Do not infer health from hardcoded labels or progress-message text.
- Preserve busy-worker behavior for long stages.
- Read-only dashboard requests must not reconcile through unsafe side effects.
- Any repair command must support dry-run and exact targeting.

## Done criteria

- Queue health is derived from real structured state.
- Active-job totals remain correct above five jobs.
- No stale batch is presented as active without an explicit stale warning.
- Channel/video counts agree across dashboard, library, and channel detail.
- Delivery and subscription warnings are visible in the Operations contract.
- Focused tests cover healthy, idle, busy, stale, degraded, and failure states.

## Validation

- Added `app/services/operations_dashboard.py` as the read-only aggregate and
  queue-health contract, plus `GET /api/operations/summary`.
- Dashboard counts are no longer coupled to display-query limits.
- Celery queue coverage distinguishes idle, ready, busy, degraded-busy, and
  unavailable states without mutating worker or job state.
- Active batches with terminal, stale, or missing active child jobs receive an
  explicit warning rather than appearing normally active.
- Failed report delivery, subscription polling failures, and visible failed jobs
  are exposed as structured warning counts.
- Library and channel detail views use counts derived from linked videos instead
  of the cached `channels.video_count` field.
- Focused service/route/rendering validation: `94 passed`.
- Default non-mutating suite: `1262 passed, 12 skipped`.
- Live API and desktop/mobile Chrome QA passed on 2026-07-21; the live contract
  correctly reported degraded-but-progressing worker coverage and four stale
  batch warnings. No page-level horizontal overflow or browser exception was
  observed.
