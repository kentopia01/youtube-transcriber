# Phase 4: Hybrid Search (BM25 + Vector RRF)

## Goal
Add hybrid search combining PostgreSQL full-text search (BM25) with vector cosine similarity using reciprocal rank fusion (RRF), as specified in Phase 4 of EMBEDDING_UPGRADE_PLAN.md.

## Assumptions
- Phases 1-3 are complete (768d nomic embeddings, speaker-aware chunking, re-embed script)
- PostgreSQL with pgvector is running in Docker
- No running database needed for unit tests (mock-based)

## Step-by-step Plan
1. Add `search_mode` setting to `app/config.py` (default: `hybrid`)
2. Add `search_vector` (TSVECTOR) column to EmbeddingChunk model
3. Create Alembic migration 004: tsvector column + GIN index + trigger + backfill
4. Rewrite `semantic_search()` to support 3 modes: vector, keyword, hybrid (RRF)
5. Update router to pass `query` text for hybrid/keyword modes
6. Write 22 tests for hybrid search (vector, keyword, hybrid, dispatch, RRF math, edge cases)
7. Update README with hybrid search docs, SEARCH_MODE config, test table
8. Run full test suite -- all 410 tests pass
9. Create handoff docs, commit, push

## Execution
- All steps completed as planned
- No plan deviations
- All 410 tests pass (22 new + 388 existing)
