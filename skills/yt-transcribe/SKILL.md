---
name: yt-transcribe
description: Transcribe YouTube videos — submit a URL, download audio, run Whisper locally, and generate an LLM summary. Use when asked to transcribe a YouTube video, get a transcript, summarize a YouTube video, or check transcription status. Also lists previously transcribed videos. Requires the youtube-transcriber Docker stack running on localhost:8000.
---

# yt-transcribe

Transcribe YouTube videos via the local youtube-transcriber service (FastAPI + Celery + Whisper + PostgreSQL).

## Prerequisites

The Docker stack must be running (Postgres, Redis, Web):

```bash
docker compose -f ~/Projects/youtube-transcriber/docker-compose.yml ps
```

If not running, start it:

```bash
cd ~/Projects/youtube-transcriber && docker compose up -d
```

The native worker must also be running (managed via launchd):

```bash
# Check status
launchctl print gui/$(id -u)/com.sentryclaw.yt-worker

# Start/restart
launchctl kickstart -k gui/$(id -u)/com.sentryclaw.yt-worker
```

## Commands

### Transcribe a video

```bash
bash scripts/transcribe.sh "https://www.youtube.com/watch?v=VIDEO_ID"
```

Submits the video, polls until complete, and prints the full transcription JSON.

Options:
- `--no-wait` — submit and return immediately (prints job_id for later polling)
- `--timeout 600` — max seconds to wait (default 600)

If the video was already transcribed, it returns the existing transcription immediately.

### Check job status

```bash
bash scripts/get_status.sh <job-id>
```

### List transcribed videos

```bash
bash scripts/list_videos.sh [--limit 20] [--status completed]
```

### Get a transcription by video ID

```bash
curl -s http://localhost:8000/api/transcriptions/<video-uuid> | python3 -m json.tool
```

## Output format

Transcription JSON includes:
- `full_text` — complete transcript (cleaned by LLM if enabled)
- `language_detected` — auto-detected language code
- `speakers` — list of unique speaker labels (e.g., `["SPEAKER_00", "SPEAKER_01"]`)
- `diarization_enabled` — whether speakers were detected
- `segments[]` — timestamped chunks with:
  - `start`, `end` — timestamps in seconds
  - `text` — segment text
  - `confidence` — Whisper confidence (avg_logprob)
  - `speaker` — speaker label (null if diarization disabled)
- `word_count`, `model_size`, `processing_time_seconds`

## Pipeline

```
YouTube URL → yt-dlp (download) → MLX Whisper (transcribe, Metal GPU)
  → Language Detection (whisper-tiny, first 30s)
  → Speaker Diarization (pyannote.audio, CPU) [optional]
  → LLM Cleanup (Anthropic Haiku) [optional]
  → Summarize (Anthropic Sonnet) → Embed (MiniLM)
```

## Architecture

- **Docker:** Postgres, Redis, Web (FastAPI)
- **Native macOS:** Celery worker with MLX Whisper (Apple Silicon Metal acceleration)
- Default model: `mlx-community/whisper-large-v3-turbo`

## Notes

- Audio is downloaded via yt-dlp by the native worker
- MLX Whisper runs natively on Apple Silicon with Metal acceleration
- Diarization requires HF_TOKEN and is toggleable (DIARIZATION_ENABLED)
- LLM cleanup is toggleable (TRANSCRIPT_CLEANUP_ENABLED)
- Summaries are generated via Claude Sonnet
