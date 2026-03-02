# Plan: Fix Dashboard Polling, Stuck Jobs, and Add Chat Launcher

## Goal
Fix dashboard auto-refresh (jobs-in-flight badge and Recent Jobs table don't update), fix queue polling that stops when empty, and add a "Chat with Library" search launcher widget.

## Assumptions
1. Queue widget (`#queue-content`) polls correctly via `/queue` partial every 3s on initial load
2. The "jobs in flight" badge and Recent Jobs table are outside the HTMX polling zone
3. Queue polling stops when empty because the polling trigger is conditional
4. `/search?q=` prefill already works in search.html

## Steps

### 1. Move "jobs in flight" badge into queue_content partial
- Remove static badge from index.html (Live Queue Overview header)
- Add dynamic badge at top of `partials/queue_content.html` so it updates via HTMX polling

### 2. Fix always-on queue polling
- Remove `{% if active_jobs or pending_jobs %}` guard around polling trigger in `queue_content.html`
- Change interval from 3s to 5s when idle to reduce load

### 3. Add polling to Recent Jobs table
- Create new `/partials/recent-jobs` endpoint in `pages.py`
- Extract table body into new `partials/recent_jobs.html` partial with self-polling trigger
- Wire up `#recent-jobs-body` in index.html with HTMX polling every 5s

### 4. Add "Chat with Library" launcher widget
- Add compact search form between Stats Row and Forms+Queue grid in `index.html`
- JavaScript handler redirects to `/search?q=...` (leverages existing search page)

### 5. Update tests
- Add tests for Chat with Library widget, recent-jobs polling, partial endpoint
- Fix queue polling delay assertion (3s → 5s in queue_content.html)

## Files Changed (7 including 1 new)
1. `app/templates/index.html` — chat launcher, polling on recent jobs, remove static badge
2. `app/templates/partials/queue_content.html` — add badge, always-on polling at 5s
3. `app/templates/partials/recent_jobs.html` (new) — extracted recent jobs table body
4. `app/routers/pages.py` — add `/partials/recent-jobs` endpoint
5. `tests/test_template_rendering.py` — add 3 new dashboard tests
6. `tests/test_design_system.py` — update polling delay assertion
7. `docs/` — handoff documentation
