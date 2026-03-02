# Diff Summary — Phase 8: Bug Fix + UI Restructuring

## What Changed

### Bug Fixes
- **app/services/transcription.py** — Fixed `segment.avg_log_prob` → `segment.avg_logprob` (AttributeError that broke the pipeline at transcription stage)
- **app/routers/search.py** — Fixed search endpoint to accept form-encoded data from HTMX (was requiring JSON body only)

### Layout Restructuring
- **app/templates/base.html** — Replaced top navbar with daisyUI drawer sidebar (desktop: always open, mobile: collapsible). Sidebar has logo, icon-based nav links (Dashboard, Library, Search), and footer. Active page highlighting via Jinja2 conditionals.
- **app/routers/pages.py** — Added `/library` route (combined videos + channels page), updated `/` (dashboard) to include queue data + channel count, added redirects for legacy `/submit` and `/channels` routes.
- **app/templates/library.html** — New template with daisyUI tabs for Videos (default) and Channels, replaces separate videos.html and channels.html pages.

### Dashboard Redesign
- **app/templates/index.html** — Complete redesign: 4 stat cards with colored icons (Light Able style), 3-column layout with submit forms + processing queue + recent jobs table, channel confirm modal embedded.
- **app/templates/partials/queue_content.html** — Compact version: inline batch progress, active job cards with progress bars, collapsible completed/failed sections.

### Template Updates
- **app/templates/video_detail.html** — Breadcrumb now links to `/library`, added border styling to all cards
- **app/templates/channel_detail.html** — Breadcrumb links to `/library?tab=channels`, border styling
- **app/templates/job_detail.html** — Breadcrumb links to `/` (Dashboard)
- **app/templates/partials/job_status.html** — Added border styling
- **app/templates/partials/search_results.html** — Added border styling
- **app/templates/search.html** — Updated heading style, wrapped in card
- **app/templates/error.html** — Added border styling

### Removed/Deprecated
- `/submit` route now redirects to `/`
- `/channels` route now redirects to `/library?tab=channels`
- `app/templates/submit.html` — Still exists but unused (redirect catches first)
- `app/templates/channels.html` — Still exists but unused (redirect catches first)
- `app/templates/queue.html` — Still exists for direct `/queue` access

## Files Modified (12)
1. `app/services/transcription.py` (bug fix)
2. `app/routers/pages.py` (new routes, restructuring)
3. `app/routers/search.py` (form data support)
4. `app/templates/base.html` (sidebar layout)
5. `app/templates/index.html` (dashboard redesign)
6. `app/templates/library.html` (NEW — combined videos/channels)
7. `app/templates/search.html` (styling update)
8. `app/templates/video_detail.html` (breadcrumb + borders)
9. `app/templates/channel_detail.html` (breadcrumb + borders)
10. `app/templates/job_detail.html` (breadcrumb)
11. `app/templates/partials/queue_content.html` (compact redesign)
12. `app/templates/partials/job_status.html` (border styling)
13. `app/templates/partials/search_results.html` (border styling)
14. `app/templates/error.html` (border styling)

## Risks
- Legacy bookmarks to `/submit` and `/channels` will redirect (302) rather than break
- The sidebar drawer uses `lg:drawer-open` — sidebar is always visible on desktop, hamburger menu on mobile
- Search endpoint now accepts both JSON and form-encoded data, which is slightly unconventional for a FastAPI endpoint

## Plan Deviations
- None. Implementation follows the plan.
