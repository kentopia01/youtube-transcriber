# Phase 3: Web Dashboard Chat UI

## Goal
Implement the ChatGPT-style web chat interface as specified in Phase 3 of `docs/CHAT_FEATURE_PLAN.md`.

## Assumptions
- Phase 2 chat backend (API + RAG + sessions) is complete and functional
- The existing design system (main.css tokens, surfaces, pills) should be matched
- marked.js CDN is acceptable for markdown rendering (already using CDN for htmx, tailwind, iconoir)

## Steps
1. Add chat CSS section to `app/static/css/main.css` (sidebar, messages, sources, input bar, thinking indicator, responsive)
2. Create `app/templates/chat.html` — full-page ChatGPT-style layout with sidebar + main chat area
3. Create `app/templates/partials/chat_sidebar.html` — session list grouped by date
4. Create `app/templates/partials/chat_messages.html` — message stream with markdown + source citations
5. Add `GET /chat` and `GET /chat/{session_id}` page routes to `app/routers/pages.py`
6. Add helper `_group_sessions_by_date()` for sidebar date grouping
7. Add "Chat" nav link to `app/templates/base.html` (desktop + mobile nav)
8. Override `main_class` block in base.html to allow chat page to use full viewport
9. Add 8 tests to `tests/test_template_rendering.py` for chat page rendering
10. Verify all 591 tests pass with no regressions
