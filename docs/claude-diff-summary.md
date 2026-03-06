# QAClaw Round 2: Phase 4 -- Diff Summary

## What Changed

| File | Change |
|---|---|
| `app/services/search.py` | **Bug fix**: Changed `LEFT JOIN` to `FULL OUTER JOIN` in `_hybrid_search()` so keyword-only matches are included in RRF results. Added COALESCE on all display columns. Expanded `keyword_ranked` CTE to include display columns. |
| `tests/test_search_service.py` | Added 9 tests: SQL injection patterns (keyword + hybrid), single-word query, very long query, FULL OUTER JOIN verification, COALESCE verification |
| `tests/test_hybrid_search.py` | Added 2 tests: FULL OUTER JOIN structure, COALESCE on display columns |

## Why
The `LEFT JOIN` from `vector_ranked` silently dropped items found only by BM25 keyword search. This is the exact scenario hybrid search was designed to handle (proper nouns, acronyms, jargon that vector search misses). `FULL OUTER JOIN` ensures both keyword-only and vector-only matches contribute to the final RRF score.

## Risks
- **None significant** -- the FULL OUTER JOIN is a strict superset of the previous LEFT JOIN behavior. Existing vector-found results are unchanged; keyword-only results now correctly appear.
- PostgreSQL supports FULL OUTER JOIN natively; no performance concern for the candidate pool sizes used (3x limit).

## Plan Deviations
- None. All planned review items completed.
