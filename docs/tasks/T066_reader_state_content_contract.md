# T066 - Reader State and Transcript Content Contract

## Status

Done — 2026-07-21

## Objective

Add durable reader-domain state and a deterministic, timestamp-preserving content
contract before building the transcript reader UI.

## Why it matters

The current video page renders one large transcript paragraph and stores no
reading position or reading status. The Reader needs stable blocks, progress, and
state that are independent of pipeline lifecycle fields.

## Scope

- Add a reading-state model/migration with unread, reading, later, finished, and
  archived semantics.
- Store progress percentage, last block/timestamp, and reading timestamps.
- Build deterministic transcript blocks from existing ordered segments.
- Merge segments into readable paragraphs while retaining start/end timestamps,
  speaker changes, and stable anchors.
- Add reader content/state APIs with bounded, validated updates.
- Update activity timestamps without mutating job or pipeline state.
- Define future-reader ownership compatibility without implementing T049.

## Out of scope

- Highlights, notes, and bookmarks.
- AI-generated chapters.
- Reader page styling.
- Multi-user/private reading-state authorization.

## Constraints

- Existing completed transcripts require no destructive backfill.
- Opening content must not call an LLM.
- Progress writes are debounced/idempotent and never enqueue work.
- Transcript regeneration must not corrupt reading-state records.
- Reader ownership must reuse T049 identity if available or document an explicit
  migration-compatible local-reader key; do not create a competing user model.

## Done criteria

- Existing transcripts produce ordered, readable, timestamped blocks.
- Reading state is created on demand and resumes within one block.
- Reader state is structurally separate from video/job lifecycle state.
- Migration/model/API/block-builder tests pass.
- API validation rejects invalid state transitions and out-of-range progress.

## Validation

- Migration `019` adds lane-compatible reader state with a unique local-reader
  path and bounded status/progress constraints.
- Reader blocks are deterministic, timestamp-preserving, speaker-aware, and fall
  back to existing full text without a destructive backfill.
- Resume resolves exact stable anchors first and nearest timestamps after content
  regeneration.
- `/api/reader/videos/{video_id}` and its state endpoint create/update local
  reader state without changing pipeline lifecycle state.
- Focused contract and migration suite passed; default regression gate passed at
  `1323 passed, 11 skipped` before T067 began.
