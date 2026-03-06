# Diff Summary: Embedding & Chunking Upgrade (Phases 1-3)

## What Changed

### `app/config.py`
- **Added** `embedding_model`, `embedding_dimensions`, `chunk_target_tokens`, `chunk_max_tokens` settings

### `app/services/embedding.py`
- **Replaced** entire file — new model loading with `nomic-ai/nomic-embed-text-v1.5` + `trust_remote_code=True`
- **Added** `_build_speaker_chunks()`: groups segments by speaker, merges short groups, splits long groups at sentence boundaries
- **Added** `_split_at_sentence_boundaries()`: splits text at `.!?` targeting configurable token counts
- **Replaced** fixed 500-token window chunking with speaker-aware semantic chunking
- **Added** `search_document:` prefix to chunk texts before encoding

### `app/services/search.py`
- **Replaced** direct `SentenceTransformer` instantiation with cached model using `settings.embedding_model`
- **Added** `search_query:` prefix to queries before encoding
- **Added** `speaker` field to search results SQL and return dicts

### `app/models/embedding_chunk.py`
- **Changed** `Vector(384)` to `Vector(768)`
- **Added** `speaker: Mapped[str | None]` column

### `app/tasks/embed.py`
- **Changed** segment extraction to include `speaker` field
- **Changed** EmbeddingChunk creation to pass `speaker` from chunk data

### `alembic/versions/003_upgrade_embeddings_768d_and_speaker.py` (NEW)
- Truncates existing embedding_chunks
- Drops and recreates HNSW index
- Resizes embedding column from vector(384) to vector(768)
- Adds speaker column

### `scripts/reembed_all.py` (NEW)
- Standalone script to re-embed all completed videos
- Supports `--dry-run` and `--video-id UUID` flags
- Batch commits every 10 videos

### `scripts/download_models.py`
- **Added** `download_embedding_model()` to pre-download nomic-embed-text-v1.5

### `README.md`
- Updated pipeline diagram to show nomic model
- Added "Semantic Embeddings" section describing model, chunking, and re-embed script
- Added 4 new config variables to configuration table

## Why
- all-MiniLM-L6-v2 is bottom-tier on MTEB; nomic-embed-text-v1.5 is top-5 with 768d vectors
- Fixed 500-token window chunking splits mid-sentence and mid-speaker-turn, destroying semantic coherence
- Speaker-aware chunking preserves turn boundaries for better retrieval, especially for multi-speaker content

## Risks
- **Existing embeddings are truncated** by migration 003 — search will be broken until `scripts/reembed_all.py` runs
- **nomic model is ~550MB** — first load takes longer than MiniLM. Mitigated by `download_models.py`
- **trust_remote_code=True** is required by nomic model (it uses custom code for task prefixes)

## Plan Deviations
- Phases 1 and 2 were implemented together in one commit since the chunking rewrite naturally fits with the model swap
