# YouTube Transcriber

A self-hosted web application that transcribes YouTube videos using Apple Silicon GPU acceleration, with optional speaker diarization and AI-powered transcript cleanup. Search, summarize, and chat with your transcribed content.

## What It Does

- **Transcribe** YouTube videos using MLX Whisper on Apple Silicon Metal
- **Detect language** automatically from the first 30 seconds
- **Identify speakers** via pyannote.audio diarization (optional)
- **Clean transcripts** with Anthropic Haiku — removes filler words while preserving meaning (optional)
- **Summarize** with Anthropic Sonnet
- **Search** across all transcribed content using semantic embeddings
- **Chat** with your transcript library via OpenClaw AI skills
- **Batch process** entire YouTube channels

## Architecture

```
┌─────────────────────────────────────────────┐
│              Docker Compose                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ Postgres │  │  Redis   │  │   Web    │  │
│  │ (pgvec)  │  │          │  │ (FastAPI)│  │
│  └──────────┘  └──────────┘  └──────────┘  │
└─────────────────────────────────────────────┘
        ↕ tcp            ↕ tcp
┌─────────────────────────────────────────────┐
│          Native macOS Process                │
│  ┌──────────────────────────────────────┐   │
│  │         Celery Worker                 │   │
│  │  • mlx-whisper (Metal GPU)           │   │
│  │  • pyannote.audio (CPU diarization)  │   │
│  │  • whisperX alignment                │   │
│  │  • LLM cleanup (Anthropic API)       │   │
│  │  • sentence-transformers (embed)     │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

The hybrid architecture runs database/web services in Docker while the Celery worker runs natively on macOS to access Apple Silicon Metal GPU acceleration for whisper inference.

## V2 Pipeline

```
YouTube URL → yt-dlp download
  → Language Detection (mlx-whisper tiny, first 30s)
  → Transcription (mlx-whisper large-v3-turbo, Metal GPU)
  → Speaker Diarization (pyannote.audio) [optional]
  → LLM Transcript Cleanup (Anthropic Haiku) [optional]
  → Summarization (Anthropic Sonnet)
  → Semantic Embeddings (nomic-embed-text-v1.5, 768d, speaker-aware chunks)
```

## Prerequisites

- **macOS** with Apple Silicon (M1/M2/M3/M4)
- **Docker Desktop** (for Postgres, Redis, and the web app)
- **Python 3.12+**
- **HuggingFace token** — required for speaker diarization (pyannote.audio models)
- **Anthropic API key** — required for summarization and optional transcript cleanup

## Installation & Setup

### 1. Clone and configure

```bash
git clone https://github.com/your-org/youtube-transcriber.git
cd youtube-transcriber
cp .env.example .env
# Edit .env with your API keys (ANTHROPIC_API_KEY, HF_TOKEN, etc.)
```

### 2. Start Docker services

```bash
docker compose up -d
```

This starts Postgres (port 5432), Redis (port 6379), and the web app (port 8000).

### 3. Set up the native worker

```bash
# Create virtual environment
python3.13 -m venv .venv-native
source .venv-native/bin/activate

# Install dependencies
pip install mlx-whisper pyannote.audio whisperx "celery[redis]" \
  sqlalchemy psycopg2-binary anthropic sentence-transformers \
  tiktoken yt-dlp structlog pydantic-settings pgvector alembic

# Copy and configure native worker env
cp .env.example .env.native
# Edit .env.native:
#   WORKER_MODE=native
#   TRANSCRIPTION_ENGINE=mlx
#   DATABASE_URL_SYNC=postgresql+psycopg2://transcriber:transcriber@localhost:5432/transcriber
#   REDIS_URL=redis://localhost:6379/0

# Run database migrations
DATABASE_URL_SYNC="postgresql+psycopg2://transcriber:transcriber@localhost:5432/transcriber" \
  alembic upgrade head
```

### 4. Install the worker as a launchd service

```bash
cp com.sentryclaw.yt-worker.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.sentryclaw.yt-worker.plist
launchctl kickstart gui/$(id -u)/com.sentryclaw.yt-worker
```

### 5. Open the app

Navigate to `http://localhost:8000`

## Configuration

All configuration is via environment variables. Set them in `.env` (Docker) and `.env.native` (worker).

| Variable | Default | Description |
|---|---|---|
| `WORKER_MODE` | `docker` | `native` for macOS Metal worker, `docker` for CPU-only |
| `TRANSCRIPTION_ENGINE` | `faster-whisper` | `mlx` (Apple Silicon) or `faster-whisper` (CPU) |
| `WHISPER_MODEL` | `mlx-community/whisper-large-v3-turbo` | MLX whisper model for transcription |
| `WHISPER_DETECT_MODEL` | `mlx-community/whisper-tiny` | Model for language detection (first 30s probe) |
| `WHISPER_LANGUAGE` | `auto` | Force a language code (e.g. `en`) or `auto` to detect |
| `WHISPER_MODEL_SIZE` | `base` | Model size for faster-whisper engine |
| `WHISPER_DEVICE` | `cpu` | Device for faster-whisper (`cpu` or `cuda`) |
| `WHISPER_COMPUTE_TYPE` | `int8` | Compute type for faster-whisper |
| `DIARIZATION_ENABLED` | `false` | Enable speaker diarization (requires `HF_TOKEN`) |
| `HF_TOKEN` | | HuggingFace token for pyannote.audio models |
| `TRANSCRIPT_CLEANUP_ENABLED` | `false` | Enable LLM-powered filler word removal |
| `CLEANUP_MODEL` | `claude-haiku-4-20250514` | Anthropic model for transcript cleanup |
| `ANTHROPIC_API_KEY` | | API key for summarization and cleanup |
| `DATABASE_URL` | | Async Postgres URL (for web app) |
| `DATABASE_URL_SYNC` | | Sync Postgres URL (for Celery worker) |
| `REDIS_URL` | | Redis URL (Celery broker) |
| `EMBEDDING_MODEL` | `nomic-ai/nomic-embed-text-v1.5` | Sentence-transformers embedding model |
| `EMBEDDING_DIMENSIONS` | `768` | Embedding vector dimensions |
| `CHUNK_TARGET_TOKENS` | `300` | Target chunk size in tokens |
| `CHUNK_MAX_TOKENS` | `400` | Maximum chunk size in tokens |
| `MODEL_CACHE_DIR` | `/data/models` | Cache directory for ML models |

See `.env.example` for the full list with all defaults.

## Usage

### Web UI

- **Dashboard** (`/`) — Submit videos, view stats, monitor jobs
- **Library** (`/videos`) — Browse transcribed videos
- **Search** (`/search`) — Semantic search across all transcripts
- **Queue** (`/queue`) — Monitor active and completed jobs

### API

```bash
# Submit a video for transcription
curl -X POST http://localhost:8000/api/videos \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=VIDEO_ID"}'

# Get transcription with V2 fields (language, speakers, segments)
curl http://localhost:8000/api/transcriptions/{video_id}

# Submit a channel for batch processing
curl -X POST http://localhost:8000/api/channels \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/@channel"}'
```

### Transcription API Response (V2)

```json
{
  "id": "uuid",
  "video_id": "uuid",
  "full_text": "...",
  "language": "en",
  "language_detected": "en",
  "speakers": ["SPEAKER_00", "SPEAKER_01"],
  "diarization_enabled": true,
  "segments": [
    {
      "index": 0,
      "start": 0.0,
      "end": 5.2,
      "text": "Hello everyone",
      "confidence": 0.95,
      "speaker": "SPEAKER_00"
    }
  ]
}
```

### OpenClaw Skills

Two bundled skills in `skills/` let AI agents interact with the transcriber:

**`yt-transcribe`** — Submit and monitor transcriptions:
```bash
bash skills/yt-transcribe/scripts/transcribe.sh "https://youtube.com/watch?v=..."
bash skills/yt-transcribe/scripts/list_videos.sh
bash skills/yt-transcribe/scripts/get_status.sh <job-id>
```

**`yt-chat`** — Chat with transcribed content:
```bash
python3 skills/yt-chat/scripts/chat.py --list
python3 skills/yt-chat/scripts/chat.py --video-id <uuid> -q "What were the main points?"
python3 skills/yt-chat/scripts/chat.py --video-id <uuid> -q "What did Speaker 1 say about pricing?"
python3 skills/yt-chat/scripts/chat.py --search "topic" -q "Summarize the discussion"
```

## V2 Pipeline Features

### Language Detection

The pipeline probes the first 30 seconds of audio with `mlx-whisper tiny` to detect the spoken language before running full transcription. This:
- Avoids forcing English on non-English content
- Provides the detected language in the API response
- Can be overridden by setting `WHISPER_LANGUAGE=en` (or any language code)

### Speaker Diarization

When `DIARIZATION_ENABLED=true` and `HF_TOKEN` is set:
1. **pyannote.audio** segments the audio into speaker turns
2. **whisperX** aligns word-level timestamps
3. A majority-vote algorithm assigns each transcript segment to the speaker who talks most during that segment
4. Segments get `speaker` labels (e.g., `SPEAKER_00`, `SPEAKER_01`)

Speaker diarization adds ~1x realtime overhead (runs on CPU).

### LLM Transcript Cleanup

When `TRANSCRIPT_CLEANUP_ENABLED=true` and `ANTHROPIC_API_KEY` is set:
- Sends transcript segments through Anthropic Haiku
- Removes filler words (um, uh, you know, basically, etc.)
- Preserves meaning, timing, and speaker labels
- Non-fatal: if the API call fails, the pipeline continues with the original text
- Adds ~10-15 seconds per video

### Semantic Embeddings

Transcripts are chunked and embedded for semantic search using `nomic-ai/nomic-embed-text-v1.5`:
- **768-dimensional** vectors (upgraded from 384d MiniLM)
- **Speaker-aware chunking** — chunks respect speaker turn boundaries when diarization is available
- **Sentence-boundary splitting** — long monologues split at sentence boundaries, not mid-word
- **Asymmetric retrieval** — uses `search_document:` prefix for chunks, `search_query:` prefix for queries
- **Configurable chunk size** — target 300 tokens, max 400 tokens (via `CHUNK_TARGET_TOKENS`, `CHUNK_MAX_TOKENS`)

To re-embed all existing videos after upgrading:
```bash
python scripts/reembed_all.py              # re-embed all completed videos
python scripts/reembed_all.py --dry-run    # preview without writing
python scripts/reembed_all.py --video-id UUID  # re-embed a single video
```

## Worker Management

```bash
# Check worker status
launchctl print gui/$(id -u)/com.sentryclaw.yt-worker

# Restart worker
launchctl kickstart -k gui/$(id -u)/com.sentryclaw.yt-worker

# View logs
tail -f /tmp/yt-worker/yt-worker.log

# Stop worker
launchctl bootout gui/$(id -u)/com.sentryclaw.yt-worker
```

## Development

### Running Tests

```bash
source .venv-native/bin/activate
pip install fastapi httpx jinja2 python-multipart  # test dependencies

# Run all tests
python -m pytest tests/ -v

# Run specific test files
python -m pytest tests/test_alignment.py -v
python -m pytest tests/test_v2_smoke.py -v  # requires Docker services running
```

### Test Structure

| File | Tests | Description |
|---|---|---|
| `test_alignment.py` | Alignment & speaker merge | `_find_speaker()` majority vote, `align_and_merge()` edge cases |
| `test_config.py` | Configuration | V2 config defaults, engine selection, native vs Docker |
| `test_pipeline_chain.py` | Pipeline construction | Chain order, step inclusion, video ID passing |
| `test_transcription_engine.py` | Engine selection | MLX/faster-whisper factory, language detection |
| `test_diarization.py` | Diarization logic | Speaker overlap, boundary handling |
| `test_transcript_cleanup.py` | LLM cleanup | Chunking, speaker label handling, API fallback |
| `test_v2_smoke.py` | Integration smoke tests | Docker services, API V2 fields, end-to-end submission |
| `test_api_endpoints.py` | API validation | Input validation, search, job cancel/retry |
| `test_task_orchestration.py` | Celery pipeline | Chain construction, batch progress |
| `test_filler_removal.py` | Regex filler removal | Legacy filler word cleaning (V1 fallback) |
| `test_template_*.py` | UI templates | Design system, rendering, HTMX attributes |

### Auto Deploy

The repo includes `.github/workflows/deploy-main.yml` for auto-deploy on push to `main`. Set these GitHub Actions secrets:

- `DEPLOY_HOST` — SSH host/IP
- `DEPLOY_USER` — SSH username
- `DEPLOY_SSH_KEY` — SSH private key
- `DEPLOY_PORT` — SSH port (optional, defaults to 22)
- `DEPLOY_APP_DIR` — Absolute path to repo on server

## Troubleshooting

### Worker not processing jobs

1. Check worker is running: `launchctl print gui/$(id -u)/com.sentryclaw.yt-worker`
2. Check Redis connection: `redis-cli -h localhost ping`
3. Check logs: `tail -f /tmp/yt-worker/yt-worker.log`
4. Verify `.env.native` has correct `REDIS_URL` and `DATABASE_URL_SYNC`

### Diarization not working

- Ensure `DIARIZATION_ENABLED=true` in `.env.native`
- Ensure `HF_TOKEN` is set with a valid HuggingFace token
- Accept the pyannote model license at https://huggingface.co/pyannote/speaker-diarization-3.1

### Docker web container shows old API

- Rebuild: `docker compose build web && docker compose up -d web`
- Or quick-fix: `docker cp app/routers/transcriptions.py youtube-transcriber-web-1:/app/app/routers/ && docker restart youtube-transcriber-web-1`

### MLX whisper model download slow

First run downloads ~3GB for `whisper-large-v3-turbo`. Models are cached in `MODEL_CACHE_DIR`. Subsequent runs are fast.

### Search returns 503

The embedding model needs to load on first search query. Wait a few seconds and retry. If persistent, check worker logs for model download errors.

## Performance

| Video Length | Transcription (MLX Metal) | With Diarization | With Cleanup |
|---|---|---|---|
| 10 min | ~1-2 min | +10 min | +10s |
| 30 min | ~3-5 min | +30 min | +12s |
| 1 hour | ~6-10 min | +60 min | +15s |

MLX on Apple Silicon is dramatically faster than faster-whisper on CPU. Diarization runs on CPU and adds ~1x realtime overhead.

## Documentation

- **User guide:** [`docs/user-guide.md`](docs/user-guide.md)
- **V2 pipeline plan:** [`docs/PLAN-v2-pipeline.md`](docs/PLAN-v2-pipeline.md)
- **Implementation plan:** [`docs/claude-plan.md`](docs/claude-plan.md)
