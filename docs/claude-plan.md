# QAClaw Phase 1 Review Plan

## Goal
Review and test all Phase 1 (Toggle System) changes for the Chat with Transcripts feature.

## Assumptions
- Phase 1 was implemented by BuildClaw in commit 1f09505
- All changes are on main branch
- Pre-existing test failure in test_config.py (stale model ID) unrelated to Phase 1

## Steps
1. Read CHAT_FEATURE_PLAN.md Phase 1 spec
2. Code review: migration 005, toggle API endpoints, search filter, UI toggles, CSS
3. Verify: toggle persistence, channel bulk-update, search filter in all 3 modes, HTMX, dimming CSS
4. Check edge cases: 404 for nonexistent resources, missing/invalid body, empty channel, all-disabled search
5. Add missing tests for uncovered edge cases (7 new tests)
6. Fix pre-existing broken test (stale model ID in test_config.py)
7. Run full test suite — 443 passed, 0 failed
8. Commit and push
