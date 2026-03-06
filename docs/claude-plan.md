# QAClaw Round 2: Phase 4 Hybrid Search Review

## Goal
Code review, test, and fix Phase 4 (Hybrid Search) implementation per QACLAW_TASK.md Round 2.

## Assumptions
- Phase 4 code is committed and passing tests
- Mock-based unit tests (no live PostgreSQL needed)

## Step-by-step Plan
1. Code review all Phase 4 changes (migration, search service, config, model, tests)
2. Verify hybrid search RRF combination of BM25 + vector scores
3. Verify search_mode config toggle for all 3 modes (vector / hybrid / keyword)
4. Verify tsvector column + GIN index + trigger in migration
5. Check edge cases: special chars, empty results, single-word, long queries, SQL injection
6. Verify vector-only mode matches pre-Phase-4 behavior
7. Add missing tests, fix bugs
8. Run full test suite
9. Create handoff docs, commit, push

## Execution

### Bug Found & Fixed
- **FULL OUTER JOIN bug**: `_hybrid_search()` used `LEFT JOIN keyword_ranked` from `vector_ranked`, meaning keyword-only matches (items found by BM25 but outside top 3x vector candidates) were silently dropped. This defeats the core purpose of hybrid search. Fixed to `FULL OUTER JOIN` with COALESCE on all display columns and both rank components.

### Tests Added (9 new)
- `test_hybrid_search_single_word_query` - single-word queries work
- `test_hybrid_search_very_long_query` - ~400-word queries don't crash
- `test_keyword_search_sql_injection_patterns` - 5 injection patterns safely parameterized
- `test_hybrid_search_sql_injection_patterns` - injection patterns in hybrid mode
- `test_uses_full_outer_join` - SQL contains FULL OUTER JOIN (x2, both test files)
- `test_keyword_ranked_has_display_columns` - COALESCE on display columns
- `test_both_rrf_components_use_coalesce` - both rank components COALESCE to 0
- `test_coalesce_on_display_columns` - in test_hybrid_search.py

### Results
- All 419 tests pass (9 new + 410 existing), 0 failures
- No plan deviations
