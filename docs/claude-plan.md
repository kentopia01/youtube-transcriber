# YouTube Transcriber — Implementation Plan

## Goal
Build a full-stack application that downloads YouTube audio (single video or entire channel), transcribes it locally with faster-whisper, summarises via Claude API, and provides a searchable web portal with semantic search via pgvector.

## Assumptions
- Docker and Docker Compose are available on the host
- PostgreSQL with pgvector extension for vector similarity search
- Redis for Celery task queue broker
- Claude API key will be provided via .env for summarization
- faster-whisper runs on CPU (configurable for GPU)
- sentence-transformers/all-MiniLM-L6-v2 for 384-dim embeddings

## Tech Stack
| Layer | Choice |
|---|---|
| Backend | Python 3.12 + FastAPI |
| Frontend | Jinja2 + HTMX + Pico CSS (dark theme) |
| Transcription | faster-whisper (CTranslate2, CPU) |
| LLM | Claude API (sonnet) for summarisation |
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 (384-dim) |
| Search | PostgreSQL + pgvector (HNSW index) |
| Task queue | Celery + Redis |
| Infra | Docker Compose (postgres, redis, web, worker, flower) |

## Implementation Steps

### Phase 1: Foundation (DONE)
- [x] Project scaffold, Docker Compose, Dockerfiles, pyproject.toml
- [x] Config (pydantic-settings), database setup (SQLAlchemy async)
- [x] All ORM models: Channel, Video, Transcription, TranscriptionSegment, Summary, EmbeddingChunk, Job, Batch
- [x] Alembic initial migration with pgvector extension + HNSW index
- [x] FastAPI app factory with Jinja2 templates and Pico CSS

### Phase 2: Transcription Pipeline (DONE)
- [x] services/youtube.py — yt-dlp download + metadata extraction + channel discovery
- [x] services/transcription.py — faster-whisper with singleton model cache
- [x] tasks/download.py, tasks/transcribe.py — Celery tasks with status tracking
- [x] Video detail page with timestamped transcript segments
- [x] Video list page with pagination and HTMX

### Phase 3: Summarisation (DONE)
- [x] services/summarization.py — Claude API with chunked fallback for long transcripts
- [x] tasks/summarize.py — Celery task
- [x] Summary display on video detail page

### Phase 4: Semantic Search (DONE)
- [x] services/embedding.py — 500-token chunks with 50-token overlap, batch encoding
- [x] tasks/embed.py — Full pipeline chain completion
- [x] services/search.py — pgvector cosine similarity search
- [x] Search page with HTMX active search (500ms debounce)

### Phase 5: Channel Support & Queue (DONE)
- [x] tasks/channel_sync.py — Channel video discovery
- [x] Channel confirmation dialog — select/deselect videos before processing
- [x] Batch processing (max 50 videos per batch)
- [x] Channel pages (list + detail)
- [x] Processing queue page with live HTMX polling (3s)
- [x] Job detail page with pipeline step visualization

### Phase 6: Polish (DONE)
- [x] Error handling and graceful degradation
- [x] Unit tests for YouTube service and embedding logic
- [x] Docker build verification
- [x] Migration verification
- [x] All routes verified returning 200
