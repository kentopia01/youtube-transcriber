# Plan: Job Titles, Clean Transcripts, Nav Cleanup, DB Reset

## Goal
Show video titles on jobs instead of "pipeline", clean filler words from transcripts, remove redundant Videos/Channels nav tabs, rename Search to "Chat with Library", and reset the database.

## Assumptions
1. Job model already has a `video` relationship
2. All Job queries in pages.py need eager loading added
3. Templates use `job.job_type` for display — switch to `job.display_name`
4. Transcript segments view is being replaced with a simple full-text paragraph
5. Filler word removal is applied at transcription time

## Steps

### 1. Job Display Names
- Add `display_name` property to `app/models/job.py` (shows video title truncated to 60 chars, falls back to job_type)
- Add `.options(selectinload(Job.video))` to all 10 Job queries in `app/routers/pages.py`
- Replace `{{ job.job_type }}` with `{{ job.display_name }}` in index.html, queue_content.html, job_status.html
- Change table header "Type" to "Job" in index.html

### 2. Clean Transcript Display
- Add `clean_filler_words()` function to `app/services/transcription.py` (regex-based removal of um, uh, you know, I mean, basically, kind of, sort of, context-aware like/right/so)
- Apply to `full_text` in `transcribe_audio()` before returning
- Replace collapsible + segments in `video_detail.html` with single `<p>` for `full_text`

### 3. Nav Cleanup
- Remove Videos and Channels links from both desktop and mobile nav in `base.html`
- Rename Search button to "Chat with Library" with `iconoir-chat-bubble` icon (desktop + mobile)
- Update `search.html` page title and heading

### 4. Database Reset
- `alembic downgrade base && alembic upgrade head`

### 5. Test Updates
- Update `_make_job` in test_template_rendering.py to include `video` + `display_name`
- Update nav assertions (remove /videos, /channels; add "Chat with Library")
- Fix test_feature_smoke.py "Semantic Search" assertion
- Create `tests/test_filler_removal.py` with 18 tests

## Files Changed (12)
1. `app/models/job.py`
2. `app/routers/pages.py`
3. `app/services/transcription.py`
4. `app/templates/base.html`
5. `app/templates/search.html`
6. `app/templates/video_detail.html`
7. `app/templates/index.html`
8. `app/templates/partials/queue_content.html`
9. `app/templates/partials/job_status.html`
10. `tests/test_template_rendering.py`
11. `tests/test_feature_smoke.py`
12. `tests/test_filler_removal.py` (new)
