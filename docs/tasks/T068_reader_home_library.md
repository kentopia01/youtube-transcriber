# T068 - Reader Home and Reading Library

## Status

Done — implemented and live-validated on 2026-07-21

## Objective

Make Reader the useful daily landing experience for deciding what to read next
and resuming unfinished transcripts.

## Why it matters

A reader needs continuity and triage, not total-library vanity metrics. Continue
Reading, Recently Ready, unread state, and reading length reduce the effort of
choosing and returning to content.

## Scope

- Make `/` Reader Home after the workspace boundary is ready.
- Add Continue Reading based on durable reader progress.
- Add Recently Ready/Unread, Later, Finished, Quick Reads, and Long Reads.
- Add channel and reading-status filters, sorting, and search entry.
- Show progress, estimated reading time, channel, summary preview, and report
  readiness on document cards.
- Add a compact Operations alert only when structured T064 warnings exist.
- Provide accessible mobile list/card behavior and useful empty states.

## Out of scope

- Queue controls on Reader Home.
- Raw worker/job/report diagnostics.
- Highlights notebook.
- Custom query-language views in v1.

## Constraints

- Reader Home stays useful when Operations is healthy and idle.
- Operational warnings link into Operations rather than duplicating controls.
- Existing 590+ completed transcripts remain browsable without backfill.

## Done criteria

- Partially read items appear in Continue Reading with correct progress.
- Newly completed unread items appear in Recently Ready.
- Later/Finished actions update the expected views.
- Filters and pagination remain usable with the current corpus size.
- Reader Home contains no queue mutation controls.
- Desktop/mobile/browser/accessibility tests pass.

## Validation

- Reader Home now provides Continue Reading, Recently Ready, and Saved for
  Later shelves from durable local reader state, with a compact warning only
  when the structured Operations contract reports one.
- The Reader library is limited to completed/readable documents and supports
  explicit status, length, channel, sort, title-search, and pagination inputs.
- Reader cards expose channel, estimated reading time, summary preview, report
  readiness, reading status, and progress; pagination preserves all selected
  filters.
- Reader Home rendering tests assert all three shelves and the absence of queue
  mutation controls.
- Final repository validation passed `1350 passed, 11 skipped`; the expanded
  live matrix passed `33/33` HTTP and `30/30` desktop/mobile browser checks.
