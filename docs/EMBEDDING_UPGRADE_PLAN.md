# Embedding & Chunking Upgrade Plan

**Project:** youtube-transcriber  
**Date:** 2026-03-06  
**Status:** Ready for implementation  
**Assignee:** BuildClaw  

---

## Goal

Upgrade the embedding pipeline from basic fixed-window chunking with a weak model to speaker-aware semantic chunking with a modern embedding model, significantly improving search/retrieval quality for the yt-chat and semantic search features.

---

## Current State

| Component | Current | Problem |
|---|---|---|
| Embedding model | `all-MiniLM-L6-v2` (384d, 22M params) | Bottom-tier on MTEB; poor at nuanced semantic matching |
| Chunking | Fixed 500-token window, 50-token overlap | Splits mid-sentence, mid-speaker-turn; no semantic coherence |
| Vector column | `Vector(384)` in pgvector | Locked to 384d model |
| Search | Pure cosine similarity | Misses exact keyword matches (names, jargon) |

---

## Phases

### Phase 1: Upgrade Embedding Model
**Scope:** Replace `all-MiniLM-L6-v2` with `nomic-ai/nomic-embed-text-v1.5`

**Why nomic-embed-text-v1.5:**
- 768 dimensions (vs 384) — much richer representations
- Top 5 on MTEB (as of 2025), MIT licensed
- Supports task prefixes (`search_query:` / `search_document:`) for asymmetric retrieval
- 8192 token context window (vs 256 for MiniLM) — can embed larger chunks
- Runs well on CPU/MPS locally via sentence-transformers

**Changes required:**
1. `app/services/embedding.py` — swap model name, add `search_document:` prefix when embedding chunks
2. `app/services/search.py` — swap model name, add `search_query:` prefix when encoding queries
3. `app/models/embedding_chunk.py` — change `Vector(384)` → `Vector(768)`
4. Alembic migration to:
   - ALTER the `embedding_chunks.embedding` column from `vector(384)` to `vector(768)`
   - TRUNCATE existing embeddings (will be re-embedded in Phase 3)
5. `app/config.py` — add `embedding_model: str = "nomic-ai/nomic-embed-text-v1.5"` and `embedding_dimensions: int = 768`
6. Update `pyproject.toml` / requirements if `nomic` needs additional deps (check — likely just `sentence-transformers` is enough)

**Testing:**
- Unit test: embed a sample text, assert output shape is (768,)
- Unit test: search with query prefix returns results
- Integration test: submit video → verify embedding chunks have 768d vectors

---

### Phase 2: Speaker-Aware Semantic Chunking
**Scope:** Replace fixed-window chunking with speaker-turn-aware chunking

**Design:**
```
Current:  [500 tokens] [500 tokens] [500 tokens] ...  (blind window)

Proposed: [Speaker A turn(s), ~200-400 tokens] [Speaker B turn(s), ~200-400 tokens] ...
          ↳ Never split mid-speaker-turn
          ↳ Merge short consecutive turns from same speaker
          ↳ Split long single-speaker blocks at sentence boundaries
          ↳ Fallback to segment-boundary splitting for non-diarized content
```

**Algorithm:**
1. Group consecutive segments by speaker label (or treat as single-speaker if no diarization)
2. For each speaker group:
   - If ≤ 400 tokens → one chunk
   - If > 400 tokens → split at sentence boundaries (`. `, `? `, `! `) targeting 200-400 tokens
3. Overlap: instead of token-level overlap, include the last sentence of the previous chunk as context prefix (cleaner semantic boundary)
4. Each chunk stores: `speaker`, `start_time`, `end_time`, `chunk_text`, `token_count`

**Changes required:**
1. `app/services/embedding.py` — rewrite `chunk_and_embed()` with new chunking logic
2. `app/models/embedding_chunk.py` — add `speaker: str | None` column
3. Alembic migration to add `speaker` column to `embedding_chunks`
4. `app/config.py` — add `chunk_target_tokens: int = 300` and `chunk_max_tokens: int = 400`

**Testing:**
- Unit test: diarized segments → chunks respect speaker boundaries
- Unit test: non-diarized segments → falls back to sentence-boundary splitting
- Unit test: long single-speaker monologue → splits at sentences, not mid-word
- Unit test: very short turns get merged with adjacent same-speaker turns
- Edge case: single segment video, empty segments, segments with no text

---

### Phase 3: Re-embed Existing Videos
**Scope:** Management command to re-process all existing transcriptions with the new model + chunking

**Changes required:**
1. New script `scripts/reembed_all.py`:
   - Query all videos with status=completed
   - For each: delete existing embedding_chunks, re-run `chunk_and_embed()` with new logic
   - Progress logging (X/Y videos processed)
   - Batch commits (every 10 videos)
   - `--dry-run` flag to preview without writing
   - `--video-id` flag to re-embed a single video
2. Add a Celery task `tasks.reembed_video` for on-demand re-embedding from the UI (future)

**Testing:**
- Run against test DB with a few videos
- Verify old 384d chunks are replaced with 768d chunks
- Verify search still works end-to-end after re-embedding

---

### Phase 4: Hybrid Search (BM25 + Vector) — DONE
**Scope:** Add keyword search alongside vector similarity for better recall

**Why:** Pure vector search misses exact matches on proper nouns, technical terms, acronyms. Hybrid search combines the best of both.

**Design:**
1. Add `tsvector` column to `embedding_chunks` (auto-generated from `chunk_text`)
2. GIN index on the tsvector column
3. Search query runs both:
   - `ts_rank(tsvector, plainto_tsquery(query))` → BM25-style score
   - `1 - (embedding <=> query_vector)` → cosine similarity
4. Combine with reciprocal rank fusion (RRF): `score = 1/(k+rank_bm25) + 1/(k+rank_vector)` where k=60
5. Return top N by combined score

**Changes required:**
1. Alembic migration: add `search_vector tsvector` column + GIN index + trigger to auto-update on insert
2. `app/services/search.py` — rewrite `semantic_search()` to do hybrid query
3. `app/config.py` — add `search_mode: str = "hybrid"` (values: `vector`, `hybrid`, `keyword`)

**Testing:**
- Unit test: query for exact name returns results even if embedding similarity is low
- Unit test: vector-only mode still works when configured
- Integration test: search returns relevant results for both semantic and keyword queries

---

## Implementation Order

```
Phase 1 (model upgrade) → Phase 2 (chunking) → Phase 3 (re-embed) → Phase 4 (hybrid, optional)
```

Phases 1 and 2 can be developed in parallel but should be merged together before Phase 3 runs, since re-embedding should use both the new model AND new chunking.

Phase 4 is independent and can be done anytime after Phase 3.

---

## Dependencies

- `sentence-transformers` (already installed)
- `nomic-ai/nomic-embed-text-v1.5` model weights (~550MB, downloaded on first use)
- No new pip packages expected (nomic model works via sentence-transformers)

## Risks

- **Vector column resize requires re-embedding** — existing search will be broken between Phase 1 deploy and Phase 3 completion. Mitigate by running Phases 1-3 in one deployment.
- **nomic model is larger** — first load will take longer. Pre-download in `scripts/download_models.py`.
- **Chunking changes affect chat context** — yt-chat skill builds context from chunks; verify it still works with new chunk sizes.

---

## Acceptance Criteria

- [ ] Embedding model is `nomic-embed-text-v1.5` with 768d vectors
- [ ] Chunks respect speaker turn boundaries when diarization is available
- [ ] Chunk target size is 200-400 tokens (configurable)
- [ ] All existing videos are re-embedded with new model + chunking
- [ ] Semantic search returns noticeably better results (manual spot check)
- [ ] All existing tests pass + new tests for chunking logic
- [ ] README updated with new model/chunking details
