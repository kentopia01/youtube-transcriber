# Phase 3 Diff Summary: Web Dashboard Chat UI

## What Changed

### New Files
- `app/templates/chat.html` — Main chat page template (ChatGPT-style layout)
  - Left sidebar with session list, "New Chat" button
  - Main chat area with message stream, markdown rendering (marked.js)
  - Source citation expandable cards
  - Input bar with auto-resize textarea, Enter to send
  - "Thinking..." animation while waiting for API response
  - Inline session rename (double-click), delete with confirm
  - Mobile responsive: sidebar slides in/out on small screens
- `app/templates/partials/chat_sidebar.html` — Session list grouped by date
- `app/templates/partials/chat_messages.html` — Server-rendered messages for initial page load

### Modified Files
- `app/static/css/main.css` — Added section 32 (Chat UI): ~350 lines of chat-specific styles
- `app/routers/pages.py` — Added `GET /chat` and `GET /chat/{session_id}` routes + `_group_sessions_by_date()` helper
- `app/templates/base.html`:
  - Added "Chat" nav link (desktop + mobile)
  - Changed nav action from "Chat with Library" to "Search" (icon updated)
  - Made `<main>` class overridable via `{% block main_class %}` for full-viewport chat
- `tests/test_template_rendering.py` — Added 8 tests in `TestChatPage` class

## Why
Implements Phase 3 of CHAT_FEATURE_PLAN.md — the web-facing chat UI that uses the Phase 2 API.

## Risks
- marked.js loaded from CDN — if CDN is down, markdown won't render (but raw text still shows)
- Session grouping uses server timezone (UTC) — may show "Yesterday" unexpectedly for users in different timezones
- No streaming/SSE yet — full response waits for API completion (could be slow for long answers)

## Plan Deviations
- Sidebar session grouping moved from Jinja2 template logic to Python helper (`_group_sessions_by_date`) to avoid timezone issues with naive/aware datetime mixing
- Added `{% block main_class %}` to base.html to support full-viewport chat layout without duplicating the base template
