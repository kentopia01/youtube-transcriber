# Plan: Full Frontend UI Rebuild (Phase 9)

## Goal
Complete visual rebuild of all frontend templates and CSS from daisyUI v5 sidebar layout to a Cloudflare/Fin.ai-inspired design system with dark navy top navigation, orange accents, serif headlines, corner bracket accents, and Iconoir icons.

## Assumptions
1. All backend Python code (routers, models, services, tasks) stays untouched
2. All Jinja2 template variables remain identical
3. All HTMX attributes (hx-get, hx-post, hx-trigger, hx-target, hx-swap, polling intervals) preserved verbatim
4. All JavaScript form handlers preserved verbatim
5. Existing tests are not affected (template-only changes)

## Steps

### Phase 1: Foundation
1. **Rewrite `app/static/css/main.css`** — Replace daisyUI-dependent CSS with new design tokens (CSS custom properties), component classes for navigation, cards, buttons, status pills, pipeline steps, pagination, modals, tables, forms, bracket accents
2. **Rewrite `app/templates/base.html`** — Replace sidebar drawer layout with sticky top-nav bar (dark navy `#1a1a2e`), drop daisyUI CDN + Manrope/Public Sans fonts, add Iconoir CSS CDN + Playfair Display/Inter/JetBrains Mono fonts, keep Tailwind browser CDN + HTMX

### Phase 2: Page Templates (11 files)
3. `index.html` — Hero with bracket accents, stat cards, video/channel forms, queue widget, jobs table, channel confirm dialog
4. `search.html` — Search input with debounce, result area, query pre-fill
5. `queue.html` — Page title + polling container
6. `library.html` — Tabs (Videos/Channels), video card grid, channel avatars, pagination
7. `video_detail.html` — Breadcrumb, metadata, thumbnail, description collapsible, summary, transcript segments
8. `channel_detail.html` — Breadcrumb, channel avatar, stats, video table
9. `job_detail.html` — Breadcrumb, polling container
10. `videos.html` — Page title + HTMX container
11. `submit.html` — Two-column forms + channel confirm dialog
12. `error.html` — Centered error card with icon
13. `channels.html` — Channel avatar grid

### Phase 3: Partial Templates (4 files)
14. `partials/queue_content.html` — Batch progress, active/pending/completed/failed sections, auto-refresh polling
15. `partials/job_status.html` — Pipeline step visualization, progress bar, details table, action buttons, auto-poll
16. `partials/video_list.html` — Video card grid + pagination with HTMX
17. `partials/search_results.html` — Result cards + empty state

## Design System Summary
- **Colors**: Light-mode Cloudflare-inspired with dark navy top-nav contrast
- **Typography**: Playfair Display (headlines), Inter (body), JetBrains Mono (data)
- **Icons**: Iconoir (MIT, 1600+ icons via CDN)
- **Key patterns**: Top navigation, corner bracket accents, status pills with dots, monospace kickers, surface cards with subtle shadows
