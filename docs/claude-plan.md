# QAClaw Phase 3 QA: Web Dashboard Chat UI

## Goal
QA review of Phase 3 (Web Chat UI) implementation — code review, test coverage, bug fixes.

## Assumptions
- Phase 3 implementation (BuildClaw) is complete per commit 561e92f
- All Phase 2 backend tests passing
- Review covers templates, routes, CSS, nav changes, JS interactions

## Steps
1. Read Phase 3 plan from `docs/CHAT_FEATURE_PLAN.md`
2. Code review: `chat.html`, `chat_sidebar.html`, `chat_messages.html`, page routes, CSS, `base.html` nav
3. Verify page routes return 200 for `/chat` and `/chat/{session_id}`
4. Verify new chat creates session via API and redirects correctly
5. Verify send message flow (fetch POST, display response, source cards)
6. Verify sidebar session list groups by date correctly
7. Verify delete/rename session works in sidebar
8. Check markdown rendering script (marked.js) included, source citation card structure
9. Check responsive sidebar collapse logic present
10. Check CSS matches existing design system (no conflicting styles)
11. Fix any bugs, add missing tests
12. Run full suite: `.venv/bin/pytest -v`
13. Update handoff docs and commit
