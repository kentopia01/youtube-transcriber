---
name: yt-transcribe
description: Transcribe YouTube videos and channel/profile URLs via the local youtube-transcriber service, wait for completion, and optionally email the results using Nora's Gmail account with a fixed template. Use when asked to transcribe a YouTube video, process a creator/channel/profile URL, summarize a YouTube video, email a transcript/summary, check transcription status, or list previously transcribed videos. Requires the youtube-transcriber stack on localhost:8000 and `gog` for email sending.
---

# yt-transcribe

Transcribe YouTube videos via the local youtube-transcriber service (FastAPI + Celery + Whisper + PostgreSQL), with routing for single-video URLs vs channel/profile URLs and a fixed-template email send path.

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

### Quick video transcription

```bash
bash scripts/transcribe.sh "https://www.youtube.com/watch?v=VIDEO_ID"
```

Submits a single video URL, polls until complete, and prints the full transcription JSON.

Options:
- `--no-wait` — submit and return immediately (prints job_id for later polling)
- `--timeout 600` — max seconds to wait (default 600)

If the video was already transcribed, it returns the existing transcription immediately.

### Route video vs channel/profile and prepare or send email

```bash
python3 scripts/process_and_email.py "<YOUTUBE_URL>" --to me --pretty
```

This is the **canonical path** for all YouTube transcription + email workflows. The OpenClaw skill `yt-transcribe-email` delegates to this script.

Behavior:
- **Video URL** → submits to `/api/videos`, waits, fetches transcription
- **Channel/profile URL** → calls `/api/channels` to discover videos, then submits each selected video to `/api/videos`, waits for each result, and builds one digest
- **Empty channel** → if no videos are discovered, returns a clear "no videos found" payload instead of failing silently
- **Recipient mapping** → `--to me` maps to a configurable email (default: `kenneth@01-digital.com`). See [Recipient Configuration](#recipient-configuration) below.
- **Email sender** → all sends go through `nora@01-digital.com`
- **Transcript policy** → emails are **summary-first by default**. Full transcript is only included when `--include-transcript` is passed.
- **Retry/backoff** → all HTTP requests use exponential backoff (3 retries, starting at 1s) for transient failures (5xx, timeouts, network errors). 4xx errors (except 429) fail immediately.
- **Template** → the email always uses the same fixed text + HTML template, styled after the youtube-transcriber frontend (navy header, orange accents, Playfair/Inter-inspired hierarchy, soft bordered cards)

Useful options:
- `--send` — actually send the email via `gog`
- `--to <email|me>` — recipient email; use `me` for Ken
- `--include-transcript` — include full transcript in the email body (default: summary only)
- `--channel-limit 5` — number of discovered videos to process for channel/profile URLs
- `--timeout 3600` — max seconds to wait per video
- `--pretty` — pretty-print the JSON payload

Examples:

```bash
# Prepare but do not send (summary only)
python3 scripts/process_and_email.py "https://www.youtube.com/watch?v=VIDEO_ID" --to me --pretty

# Include full transcript
python3 scripts/process_and_email.py "https://www.youtube.com/watch?v=VIDEO_ID" --to me --include-transcript --pretty

# Discover latest 3 videos from a creator profile and send the digest as Nora
python3 scripts/process_and_email.py "https://www.youtube.com/@creator" --to me --channel-limit 3 --send --pretty
```

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

## Recipient Configuration

Recipient aliases like `--to me` are resolved via a configurable mapping. Priority:

1. **`YT_RECIPIENT_MAP` env var** — JSON string, e.g. `'{"me":"alice@example.com","boss":"bob@example.com"}'`
2. **`~/.yt-transcriber-recipients.json` file** — same JSON format, saved to disk
3. **Built-in defaults** — `me`/`ken`/`self` → `kenneth@01-digital.com`

To add new aliases, create or edit `~/.yt-transcriber-recipients.json`:

```json
{
  "me": "kenneth@01-digital.com",
  "ken": "kenneth@01-digital.com",
  "alice": "alice@example.com"
}
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
  → Summarize (Anthropic Haiku) → Embed (MiniLM)
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
- The fixed email template is intentionally centralized in `scripts/process_and_email.py` so every email stays consistent
- When the user explicitly wants the result emailed, use `--send` so it is sent as Nora via `nora@01-digital.com`
- If the requester says "email it to me", use `--to me`, which maps to the configured recipient
