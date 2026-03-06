# Plan: Fix 6 Pipeline Reliability Bugs

## Goal
Fix pipeline retry reliability — make retry smart (resume from failure point), all tasks idempotent (no duplicate data on re-run), and job tracking correct (latest job gets updates).

## Assumptions
- Pipeline steps: download → transcribe → diarize → cleanup → summarize → embed
- Each step passes video_id to the next via Celery chain
- Transcription, Summary have unique constraints on video_id
- EmbeddingChunk has no unique constraint but duplicates corrupt search results

## Step-by-step Plan
1. **Create `app/tasks/helpers.py`** — shared `get_latest_pipeline_job(db, video_id)` that queries `ORDER BY created_at DESC` instead of `.first()`
2. **Bug 2 — transcribe.py idempotency** — check for existing transcription before INSERT; if exists, UPDATE it and DELETE old segments first
3. **Bug 4 — summarize.py idempotency** — check for existing summary; if exists, UPDATE instead of INSERT
4. **Bug 5 — embed.py cleanup** — DELETE existing embedding_chunks for video_id before inserting new ones
5. **Bug 3 — use latest job in ALL tasks** — replace `.filter(...).first()` with `get_latest_pipeline_job()` in download.py, transcribe.py, diarize.py, cleanup.py, summarize.py, embed.py
6. **Bug 1 — smart retry** — add `run_pipeline_from(video_id, start_from)` to pipeline.py; update retry_job() to detect resume point via `_detect_resume_point()` (checks what data exists)
7. **Bug 6 — failed video resubmission** — if existing video status is 'failed', allow re-processing instead of returning 'existing'
8. **Exponential backoff** — add `max_retries=2` with backoff to summarize and embed tasks
9. **Update tests** — fix retry test for new smart retry flow, add tests for `run_pipeline_from` partial chains
10. **Update README** — document retry behavior
