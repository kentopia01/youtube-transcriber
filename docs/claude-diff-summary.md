# Diff Summary: Dashboard Polling + Chat Launcher

## What Changed

### `app/templates/partials/queue_content.html`
- **Added** "jobs in flight" badge at top of partial (was static in index.html, never updated)
- **Removed** `{% if active_jobs or pending_jobs %}` guard around polling trigger — polling now continues even when queue is empty
- **Changed** polling interval from 3s to 5s for the self-re-poll to reduce idle load

### `app/templates/index.html`
- **Removed** static "jobs in flight" badge from Live Queue Overview header (moved into partial)
- **Replaced** inline `<tbody>` with `{% include "partials/recent_jobs.html" %}` wrapped in `#recent-jobs-body` with HTMX polling (`hx-get="/partials/recent-jobs"`, 5s interval)
- **Added** "Chat with Library" search launcher widget between Stats Row and Forms+Queue grid
- **Added** JavaScript handler for quick-search form that redirects to `/search?q=...`

### `app/templates/partials/recent_jobs.html` (NEW)
- Extracted Recent Jobs table body markup from index.html
- Includes self-polling hidden trigger for continuous updates

### `app/routers/pages.py`
- **Added** `GET /partials/recent-jobs` endpoint — lightweight query returning last 10 jobs as partial HTML

### `tests/test_template_rendering.py`
- **Added** `test_dashboard_has_recent_jobs_polling` — checks for `#recent-jobs-body` and HTMX attributes
- **Added** `test_dashboard_has_chat_launcher` — checks for search form elements
- **Added** `test_recent_jobs_partial_endpoint` — validates `/partials/recent-jobs` returns 200 with job data
- **Updated** `test_dashboard_has_queue_polling` — relaxed delay assertion (partial now uses 5s)

### `tests/test_design_system.py`
- **Updated** `test_auto_refresh_in_queue_content` — changed expected polling delay from 3s to 5s

## Why
- Dashboard was rendering stale data — the jobs-in-flight counter and Recent Jobs table loaded once and never refreshed
- Queue polling stopped when empty, meaning new jobs wouldn't appear until manual refresh
- Chat launcher provides quick access to semantic search from the dashboard

## Risks
- **None significant** — all changes are frontend polling and a new read-only endpoint
- The Recent Jobs partial re-queries the DB every 5s per connected client; acceptable at current scale
- No changes to job processing, models, or business logic

## Plan Deviations
- None — implementation follows the plan exactly
