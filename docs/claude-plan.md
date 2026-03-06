# Plan: Embedding & Chunking Upgrade (Phases 1-3)

## Goal
Upgrade the embedding pipeline from all-MiniLM-L6-v2 (384d) with fixed-window chunking to nomic-embed-text-v1.5 (768d) with speaker-aware semantic chunking, improving search/retrieval quality.

## Assumptions
1. No new pip packages needed (nomic model works via sentence-transformers)
2. Existing embeddings will be truncated during migration and re-embedded via script
3. Phase 4 (hybrid search) is deferred to a future task
4. The `trust_remote_code=True` flag is required for nomic model

## Steps

### Phase 1: Model Upgrade
1. Add `embedding_model`, `embedding_dimensions`, `chunk_target_tokens`, `chunk_max_tokens` to Settings
2. Swap model in `embedding.py` to `nomic-ai/nomic-embed-text-v1.5` with `search_document:` prefix
3. Swap model in `search.py` to use cached model with `search_query:` prefix
4. Change `Vector(384)` to `Vector(768)` in `embedding_chunk.py`
5. Create Alembic migration 003: truncate, resize vector column, add speaker column, rebuild HNSW index

### Phase 2: Speaker-Aware Chunking
1. Rewrite `chunk_and_embed()` with speaker-turn-aware chunking algorithm
2. Add `_build_speaker_chunks()`: groups consecutive segments by speaker, merges short groups, splits long groups at sentence boundaries
3. Add `_split_at_sentence_boundaries()`: splits text at `.!?` targeting configurable token counts
4. Pass `speaker` from TranscriptionSegment through task to EmbeddingChunk
5. Include `speaker` in search results
6. Write 11 unit tests for chunking logic

### Phase 3: Re-embed Script + Supporting Changes
1. Create `scripts/reembed_all.py` with `--dry-run` and `--video-id` flags, batch commits
2. Update `scripts/download_models.py` to pre-download nomic model
3. Update README with new model details, chunking description, config variables

## Files Changed (8 modified, 2 new)
1. `app/config.py` — add 4 embedding config vars
2. `app/services/embedding.py` — new model + speaker-aware chunking
3. `app/services/search.py` — new model + search_query: prefix + speaker in results
4. `app/models/embedding_chunk.py` — Vector(768) + speaker column
5. `app/tasks/embed.py` — pass speaker from segments to chunks
6. `tests/test_embedding_service.py` — 11 new chunking tests
7. `alembic/versions/003_upgrade_embeddings_768d_and_speaker.py` (NEW) — DB migration
8. `scripts/reembed_all.py` (NEW) — re-embed script
9. `scripts/download_models.py` — add nomic model download
10. `README.md` — document new embedding model, config vars, re-embed script
