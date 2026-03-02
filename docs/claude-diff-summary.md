# Diff Summary: Job Titles, Clean Transcripts, Nav Cleanup, DB Reset

## What Changed

### `app/models/job.py`
- Added `display_name` property: returns video title (truncated to 60 chars) or falls back to `job_type`

### `app/routers/pages.py`
- Added `.options(selectinload(Job.video))` to all 10 `select(Job)` queries (dashboard: 5, job_detail: 1, queue_page: 4)
- Simplified job_detail: uses `job.video` from eager load instead of separate video query

### `app/services/transcription.py`
- Added `import re`
- Added `clean_filler_words(text)` function with regex-based removal of filler words (um, uh, uhm, umm, you know, I mean, basically, kind of, sort of) and context-aware removal (like before comma/pronoun, right before comma/question, so before comma)
- Applied `clean_filler_words()` to `full_text` before returning from `transcribe_audio()`

### `app/templates/base.html`
- Removed Videos (`/videos`) and Channels (`/channels`) nav links from both desktop and mobile nav
- Changed Search button text to "Chat with Library" with `iconoir-chat-bubble` icon (desktop + mobile)

### `app/templates/search.html`
- Changed page title from "Search" to "Chat with Library"
- Changed heading from "Semantic Search" to "Chat with Library"

### `app/templates/video_detail.html`
- Replaced collapsible full-text section + segments loop (with timestamps) with a single `<p>` paragraph showing `transcription.full_text`

### `app/templates/index.html`
- Changed table header "Type" to "Job"
- Changed `{{ job.job_type }}` to `{{ job.display_name }}` in table rows

### `app/templates/partials/queue_content.html`
- Changed all 4 occurrences of `{{ job.job_type }}` to `{{ job.display_name }}`

### `app/templates/partials/job_status.html`
- Changed header and details table to use `{{ job.display_name }}` (kept `job.job_type` in pipeline logic check)

### `tests/test_template_rendering.py`
- Updated `_make_job` to include `video` SimpleNamespace with title and computed `display_name`
- Updated `test_nav_links_present` to assert `/videos` and `/channels` are NOT in nav, and "Chat with Library" IS present

### `tests/test_feature_smoke.py`
- Changed "Semantic Search" assertion to "Chat with Library"

### `tests/test_filler_removal.py` (new)
- 18 tests for `clean_filler_words()`: standalone fillers, context-aware removals, punctuation cleanup, empty string, no-op, case insensitivity

## Why
- Jobs showing "pipeline" everywhere was unhelpful — video titles give immediate context
- Transcript segments with timestamps added clutter for reading — a clean paragraph is more useful
- Filler words from speech recognition degrade readability
- Videos and Channels nav were redundant with the Library tab
- "Search" was a generic label — "Chat with Library" better describes semantic search intent

## Risks
- `clean_filler_words()` uses simple regex patterns which may occasionally remove valid words in edge cases (e.g., "I like you" would be affected by the "like + pronoun" rule). The patterns are conservative but not perfect.
- `selectinload(Job.video)` adds an extra SQL query per Job query batch. This is a non-issue at current scale but could matter with thousands of concurrent jobs.
- Routes for `/videos` and `/channels` still exist and work — only nav links were removed. Internal links to these routes from other pages still function.

## Database Reset
- Ran `alembic downgrade base && alembic upgrade head` — all tables dropped and recreated clean.

## Plan Deviations
- Also updated `tests/test_feature_smoke.py` (not in original plan) — it asserted "Semantic Search" which broke.
