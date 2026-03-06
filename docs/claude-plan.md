# QAClaw Round 1: Phases 1-3 Review & Testing

## Goal
Review, test, and fix the Embedding & Chunking Upgrade (Phases 1-3) implemented by BuildClaw.

## Assumptions
- All Phase 1-3 code is already merged to main
- No running database to test migrations against (verified by code review only)
- ML model not available in test env (tests use mocks)

## Step-by-step Plan
1. Code review all changed files against EMBEDDING_UPGRADE_PLAN.md
2. Verify Alembic migration 003 is correct and reversible
3. Review existing test coverage in tests/test_embedding_service.py
4. Fix any bugs found during review
5. Write additional unit tests for uncovered edge cases
6. Add config defaults tests for new embedding settings
7. Run full test suite, fix failures
8. Create handoff docs, commit, push

## Execution
- **Bug found**: `_split_at_sentence_boundaries` had dead code -- `target_tokens` was ignored (only `max_tokens` triggered flushes). Fixed by replacing `pass` with actual flush logic.
- **Tests added**: 16 new tests covering edge cases, mocked `chunk_and_embed`, config defaults.
- **All 366 tests pass** (0 failures).
