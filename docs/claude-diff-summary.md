# Diff Summary — YouTube Transcriber

## What Changed
Full greenfield implementation of the YouTube Transcriber application with 60+ files.

### Infrastructure (6 files)
- `docker-compose.yml` — 5 services: postgres (pgvector), redis, web, worker, flower
- `Dockerfile` — Lightweight web image (Python 3.12 + FastAPI deps)
- `Dockerfile.worker` — Heavy worker image (includes ffmpeg, faster-whisper, sentence-transformers)
- `pyproject.toml` — Dependencies with `[worker]` optional extra for ML deps
- `.env` / `.env.example` — Configuration
- `scripts/create_extensions.sql` — pgvector + uuid-ossp extensions

### Database (3 files)
- `alembic.ini` + `alembic/env.py` — Alembic configuration
- `alembic/versions/001_initial_schema.py` — All 8 tables + HNSW index

### Models (8 files)
- Channel, Video, Transcription, TranscriptionSegment, Summary, EmbeddingChunk, Job, Batch

### Services (5 files)
- `youtube.py` — yt-dlp integration (download, metadata, channel discovery)
- `transcription.py` — faster-whisper with singleton model cache
- `summarization.py` — Claude API with chunk-then-consolidate for long texts
- `embedding.py` — 500-token chunking with 50-token overlap + batch encoding
- `search.py` — pgvector cosine similarity with lazy sentence-transformer import

### Tasks (6 files)
- `celery_app.py` — Celery configuration with Redis broker
- `download.py`, `transcribe.py`, `summarize.py`, `embed.py` — Pipeline tasks
- `pipeline.py` — Chain orchestration using signatures (avoids ML imports in web)
- `channel_sync.py` — Channel video discovery task

### Routers (6 files)
- `pages.py` — All HTML page routes (dashboard, submit, videos, channels, search, queue, job detail)
- `videos.py` — POST /api/videos (submit + pipeline launch)
- `channels.py` — POST /api/channels (discover) + POST /api/channels/{id}/process (batch queue)
- `search.py` — POST /api/search (semantic search)
- `jobs.py` — GET/POST job status and cancellation
- `transcriptions.py` — GET transcription with segments

### Templates (13 files)
- `base.html` — Dark theme Pico CSS + HTMX + navigation
- `index.html` — Dashboard with stats, quick submit, active jobs
- `submit.html` — Video + channel submission with confirmation dialog
- `videos.html` + `partials/video_list.html` — Paginated video grid
- `video_detail.html` — Transcript segments, summary, metadata
- `channels.html`, `channel_detail.html` — Channel grid and detail
- `search.html` + `partials/search_results.html` — Active semantic search
- `queue.html` + `partials/queue_content.html` — Live processing queue
- `job_detail.html` + `partials/job_status.html` — Pipeline step visualization

### Tests (2 files)
- `test_youtube_service.py` — URL extraction and channel detection
- `test_embedding_service.py` — Chunking logic

## Why
Implements the full YouTube Transcriber plan from phases 1-6 as a working Docker Compose application.

## Key Design Decisions
1. **Lazy ML imports**: Pipeline uses Celery signatures by name (not direct task imports) to avoid pulling faster-whisper/sentence-transformers into the web container
2. **Singleton model cache**: Whisper and embedding models loaded once per worker process
3. **Chunked summarization**: Transcripts >100k tokens are split, individually summarized, then consolidated
4. **HNSW index**: pgvector cosine similarity with HNSW for fast approximate nearest neighbor search
5. **HTMX load polling**: Job status and queue update via periodic HTMX GET requests (2-3s intervals)

## Risks
1. **Search on web container**: The web container doesn't include sentence-transformers (too heavy). Search returns 503 until the dependency is available. Could be resolved by running search encoding as a Celery task or adding a lightweight search service.
2. **No authentication**: The application has no auth. Anyone with access can submit videos.
3. **Audio storage**: Audio files accumulate in the shared volume. No automatic cleanup is implemented yet.
4. **Celery task error recovery**: Tasks retry on download failure (3 retries), but transcription/summarization/embedding failures are not retried.
5. **Batch continuation**: When a channel batch completes, the next batch doesn't auto-start yet (requires a callback or periodic check).

## Plan Deviations
- Search encoding gracefully degrades on the web container instead of including sentence-transformers in the web image (would add ~2GB to the image)
- Pipeline uses Celery signatures by name rather than direct task imports to keep web image lightweight
