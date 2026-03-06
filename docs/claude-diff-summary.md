# Phase 4: Hybrid Search -- Diff Summary

## What Changed

| File | Change |
|---|---|
| `alembic/versions/004_add_tsvector_hybrid_search.py` | New migration: adds `search_vector tsvector` column, GIN index, auto-update trigger, backfills existing rows |
| `app/models/embedding_chunk.py` | Added `search_vector` column (TSVECTOR type) |
| `app/config.py` | Added `search_mode: str = "hybrid"` setting |
| `app/services/search.py` | Rewrote with 3 search modes: `_vector_search`, `_keyword_search`, `_hybrid_search` (RRF fusion). Dispatcher `semantic_search()` routes by config or override. |
| `app/routers/search.py` | Passes `query=query` text to `semantic_search()` for BM25 matching |
| `tests/test_hybrid_search.py` | New: 21 tests covering all modes, RRF dispatch, fallbacks, config |
| `tests/test_api_endpoints.py` | Updated 4 fake_search mocks to accept `**kwargs` |
| `tests/test_feature_smoke.py` | Updated 2 fake_search mocks to accept `**kwargs` |
| `README.md` | Already had hybrid search docs (pre-populated) |

## Why
Pure vector search misses exact matches on proper nouns, technical terms, and acronyms. Hybrid BM25+vector with RRF gives best-of-both-worlds retrieval.

## Risks
- **Migration must run before hybrid mode works** -- the `search_vector` column and GIN index are required. Run `alembic upgrade head` before deploying.
- **Backfill on large tables** -- the migration backfills all existing rows. On very large datasets this could be slow; consider running during off-peak.

## Plan Deviations
- None. Implementation matches the plan exactly.
