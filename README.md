# YouTube Transcriber

A web app that lets you submit YouTube videos (or channels), transcribe audio, generate summaries, and search transcript content.

## V2 Pipeline (Current)

```
YouTube URL → yt-dlp (download)
  → Language Detection (mlx-whisper tiny, first 30s)
  → Transcription (mlx-whisper large-v3-turbo, Apple Silicon Metal)
  → Speaker Diarization (pyannote.audio, CPU) [optional]
  → LLM Transcript Cleanup (Anthropic Haiku) [optional]
  → Summarize (Anthropic Sonnet) → Embed (MiniLM)
```

### Architecture

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
│  │  • mlx-whisper (Metal-accelerated)   │   │
│  │  • pyannote.audio (CPU)              │   │
│  │  • whisperX alignment               │   │
│  │  • LLM cleanup (API calls)           │   │
│  │  • sentence-transformers (embed)     │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

- **Docker:** Postgres (pgvector), Redis, Web (FastAPI)
- **Native macOS:** Celery worker with MLX Whisper (Apple Silicon Metal acceleration)

## Documentation Map

- **Start here (nontechnical):** [`docs/user-guide.md`](docs/user-guide.md)
- **V2 pipeline plan:** [`docs/PLAN-v2-pipeline.md`](docs/PLAN-v2-pipeline.md)
- **Project implementation plan:** [`docs/claude-plan.md`](docs/claude-plan.md)

## Quick Start

### 1. Start Docker services

```bash
cp .env.example .env
# Edit .env with your API keys
docker compose up -d
```

### 2. Set up native worker

```bash
# Create venv and install dependencies
python3.13 -m venv .venv-native
source .venv-native/bin/activate
pip install mlx-whisper pyannote.audio whisperx "celery[redis]" sqlalchemy psycopg2-binary anthropic sentence-transformers tiktoken yt-dlp structlog pydantic-settings pgvector alembic

# Copy and edit native worker config
cp .env.example .env.native
# Edit .env.native: set localhost URLs, TRANSCRIPTION_ENGINE=mlx, WORKER_MODE=native

# Run migrations
DATABASE_URL_SYNC="postgresql+psycopg2://transcriber:transcriber@localhost:5432/transcriber" alembic upgrade head

# Install launchd service
cp com.sentryclaw.yt-worker.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.sentryclaw.yt-worker.plist
launchctl kickstart gui/$(id -u)/com.sentryclaw.yt-worker
```

### 3. Open the app

- `http://localhost:8000`

### Worker management

```bash
# Check worker status
launchctl print gui/$(id -u)/com.sentryclaw.yt-worker

# Restart worker
launchctl kickstart -k gui/$(id -u)/com.sentryclaw.yt-worker

# View logs
tail -f /tmp/yt-worker/yt-worker.log
```

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `WORKER_MODE` | `docker` | `native` or `docker` |
| `TRANSCRIPTION_ENGINE` | `faster-whisper` | `mlx` (Apple Silicon) or `faster-whisper` (CPU) |
| `WHISPER_MODEL` | `mlx-community/whisper-large-v3-turbo` | MLX whisper model |
| `WHISPER_DETECT_MODEL` | `mlx-community/whisper-tiny` | Language detection model |
| `WHISPER_LANGUAGE` | `auto` | Force language or auto-detect |
| `HF_TOKEN` | — | HuggingFace token for pyannote diarization |
| `DIARIZATION_ENABLED` | `false` | Toggle speaker diarization |
| `TRANSCRIPT_CLEANUP_ENABLED` | `false` | Toggle LLM transcript cleanup |
| `CLEANUP_MODEL` | `claude-haiku-4-20250514` | Model for transcript cleanup |
| `ANTHROPIC_API_KEY` | — | For summaries and cleanup |

See `.env.example` for the full list.

## Auto Deploy On Push

This repo includes `.github/workflows/deploy-main.yml` to auto-deploy on every push to `main`.

Set these GitHub Actions repository secrets before enabling it:

- `DEPLOY_HOST`: SSH host/IP of your server
- `DEPLOY_USER`: SSH username
- `DEPLOY_SSH_KEY`: private key for SSH auth
- `DEPLOY_PORT`: SSH port (optional; defaults to `22`)
- `DEPLOY_APP_DIR`: absolute path to this repo on the server

## What the App Does

- Submit a **single video URL** for full processing
- Submit a **channel URL**, choose videos, and process in batches
- View **job queue** and status updates
- Read **transcript + summary** for each processed video
- Run **semantic search** across transcript chunks
- **Speaker diarization** identifies who says what (optional)
- **LLM transcript cleanup** removes filler words intelligently (optional)

## Main Areas in the UI

- `/` Dashboard
- `/submit` Submit videos/channels
- `/videos` Video library
- `/channels` Channel library
- `/search` Semantic search
- `/queue` Active and completed jobs

## OpenClaw Skills

Two bundled skills in `skills/` let AI agents interact with the transcriber programmatically:

### `yt-transcribe` — Transcribe videos

```bash
# Submit a video and wait for transcription
bash skills/yt-transcribe/scripts/transcribe.sh "https://www.youtube.com/watch?v=VIDEO_ID"

# List all transcribed videos
bash skills/yt-transcribe/scripts/list_videos.sh

# Check job status
bash skills/yt-transcribe/scripts/get_status.sh <job-id>
```

### `yt-chat` — Chat with transcribed content

```bash
# List available videos
python3 skills/yt-chat/scripts/chat.py --list

# Ask a question about a specific video
python3 skills/yt-chat/scripts/chat.py --video-id <uuid> -q "What were the main points?"

# Speaker-aware queries (when diarization is enabled)
python3 skills/yt-chat/scripts/chat.py --video-id <uuid> -q "What did Speaker 1 say about pricing?"

# Search across all transcripts
python3 skills/yt-chat/scripts/chat.py --search "topic" -q "What was discussed?"
```

Requires `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` for the chat LLM. See each skill's `SKILL.md` for full details.

## Performance Expectations

| Scenario | V1 (base, CPU, Docker) | V2 (large-v3-turbo, MLX Metal, full pipeline) |
|---|---|---|
| 10-min video | ~3-5 min | ~5-10 min |
| 30-min video | ~8-15 min | ~15-25 min |
| 1-hour video | ~15-30 min | ~30-50 min |

MLX on Apple Silicon is dramatically faster than faster-whisper on CPU. Diarization adds ~1x realtime overhead (CPU). LLM cleanup adds ~10-15s per video.
