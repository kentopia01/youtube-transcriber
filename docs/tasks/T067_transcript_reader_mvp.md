# T067 - Transcript Reader MVP

## Status

Done — 2026-07-21

## Objective

Deliver a comfortable, responsive transcript-reading surface using the T066
content and state contracts.

## Why it matters

The current video detail page is metadata-first and renders the transcript as one
dense paragraph. A dedicated reader should make long transcripts navigable,
readable, and resumable.

## Scope

- Add `/read/{video_id}` with a semantic article layout.
- Render timestamped transcript blocks with correct YouTube deep links.
- Save and restore reading position.
- Add in-document search and jump-to-result behavior.
- Add transcript outline fallback using deterministic time sections.
- Add font size, line spacing, content width, weight, and light/paper/sepia/dark
  appearance controls.
- Add mark Later/Finished actions.
- Add keyboard navigation and mobile bottom-sheet controls.
- Link the existing video detail page to Reader without removing operator metadata.

## Out of scope

- Highlights/notes/bookmarks.
- Document-scoped AI.
- AI-generated semantic chapters.
- Page-turn animation; continuous vertical scroll is the default.

## Constraints

- Default reading column targets roughly 65-72 characters per line.
- No horizontal reading scroll at 320 CSS pixels or enlarged text.
- Reader opens without LLM or external CDN availability.
- Settings persist locally without blocking future server-side preferences.

## Done criteria

- Any completed transcript opens in Reader.
- Reload resumes within one transcript block.
- Timestamp links target the correct video time.
- Search locates and navigates to matching blocks.
- Appearance controls persist and remain WCAG-AA across themes.
- Keyboard, screen-reader, 320px, 390px, tablet, and desktop tests pass.

## Validation

- `/read/{video_id}` renders semantic, timestamped transcript blocks with a
  deterministic outline and YouTube deep links.
- Debounced progress, exact/nearest resume, Later/Finished state, in-document
  search, keyboard navigation, and persisted appearance controls are covered by
  focused service, API, template, and browser checks.
- Reader content remains local and opens without an LLM call or external
  frontend dependency.
- Migration `019` was applied to the live local database after a read-only QA
  probe exposed the missing table; the Reader document subsequently returned
  HTTP 200.
- Focused Reader/workspace/QA suite passed at `55 passed`; the expanded live
  feature matrix passed `29/29` HTTP checks and `24/24` Chromium checks across
  desktop and 320px mobile, including search and persisted sepia appearance.
