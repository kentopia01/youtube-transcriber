# QAClaw Phase 3 QA Diff Summary

## What Changed

### Modified Files
- `app/templates/chat.html`:
  - User messages: replaced `<br>` injection with `white-space:pre-wrap` for safer newline rendering
- `app/templates/partials/chat_messages.html`:
  - User messages: replaced `| replace('\n', '<br>')` with `style="white-space:pre-wrap"` (avoids Markup.replace complexity)
- `tests/test_template_rendering.py`:
  - Added `/chat` nav link assertion to `test_nav_links_present` (was missing)
  - Added 9 new chat page tests in `TestChatPage`:
    - `test_chat_page_has_marked_js` — verifies marked.js script included
    - `test_chat_page_has_mobile_sidebar_toggle` — mobile toggle, overlay, toggleSidebar
    - `test_chat_page_has_send_on_enter` — Enter key handler present
    - `test_chat_page_sidebar_shows_session` — session title rendered in sidebar
    - `test_chat_page_sidebar_date_grouping` — group label + correct group assignment
    - `test_chat_session_page_with_messages` — full message rendering with source cards, similarity %, markdown class
    - `test_chat_page_input_disabled_when_no_session` — input disabled without active session
    - `test_chat_page_main_class_override` — chat-page-shell replaces page-shell
    - `test_chat_page_new_design_markers` — new design system markers + no daisyUI
  - Added 4 unit tests for `_group_sessions_by_date` helper in `TestGroupSessionsByDate`:
    - `test_empty_sessions`, `test_today_group`, `test_multiple_groups_ordered`, `test_naive_datetime_handled`
  - Added 8 XSS + edge case tests in `TestChatXSSAndEdgeCases`:
    - XSS escaping for user messages, assistant messages, source titles, source chunks, sidebar titles
    - Newline rendering with pre-wrap
    - Empty sources don't render source toggle
  - Fixed 2 pre-existing test bugs:
    - `test_source_title_xss_escaped`: was checking raw attribute text instead of escaped HTML tags
    - `test_empty_sources_no_source_section`: was matching CSS class in JS code instead of rendered elements

## Bugs Found and Fixed
1. **User message newline rendering** (templates): `<br>` injection via Jinja2 `| replace` on Markup objects was working but fragile. Replaced with `white-space:pre-wrap` CSS — cleaner, safer, and avoids the `Markup.replace` auto-safe behavior.

## Code Review Findings (no critical bugs)
- Templates: Well-structured, consistent with existing design system
- XSS safety: autoescape=True in Jinja2, `escapeHTML()` in JS, proper `| e` filters
- Responsive: Mobile sidebar toggle + overlay + slide animation properly wired
- CSS: ~350 lines of chat-specific styles using existing design tokens (no conflicts)
- JS: Fetch-based message flow with thinking indicator, error handling, auto-scroll
- Routes: Proper session loading with `selectinload` for messages, 404 for missing sessions
- Sidebar: Date grouping handles naive/aware datetimes, correct label ordering
- Markdown: marked.js CDN with GFM + breaks, server-rendered messages use DOMContentLoaded

## Risks
- No streaming/SSE — noted from Phase 3 plan, full response waits for API completion
- marked.js CDN dependency — fallback is raw text display (graceful degradation)

## Test Results
- 612 tests pass (up from 591 — 21 new tests added, 2 pre-existing test bugs fixed)

## Plan Deviations
None — all QA steps completed as planned.
