# QAClaw Phase 1 Review Plan (Round 2)

## Goal
Second-pass QA review of Phase 1 (Toggle System) — focus on idempotency, response correctness, and missing where-clause coverage.

## Assumptions
- Phase 1 implemented in commit 1f09505, first QA pass in commit 421ceef
- All changes on main branch
- 443 tests passing at start of review

## Steps
1. Re-read CHAT_FEATURE_PLAN.md Phase 1 spec
2. Full code review: migration 005, toggle API endpoints, search filter, UI/HTMX, CSS dimming
3. Identify gaps in existing 21 toggle tests
4. Add 7 new edge case tests: idempotent toggles (video+channel), response ID correctness, channel invalid UUID, channel_id-only where clause
5. Run full test suite — 450 passed, 0 failed
6. Update handoff docs, commit, push
