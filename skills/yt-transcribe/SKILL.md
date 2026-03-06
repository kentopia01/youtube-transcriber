---
name: yt-transcribe
description: Transcribe YouTube videos — submit a URL, download audio, run Whisper locally, and generate an LLM summary. Use when asked to transcribe a YouTube video, get a transcript, summarize a YouTube video, or check transcription status. Also lists previously transcribed videos. Requires the youtube-transcriber Docker stack running on localhost:8000.
---

# yt-transcribe

Transcribe YouTube videos via the local youtube-transcriber service (FastAPI + Celery + Whisper + PostgreSQL).

## Prerequisites

The Docker stack must be running:

```bash
docker compose -f ~/Projects/youtube-transcriber/docker-compose.yml ps
```

If not running, start it:

```bash
cd ~/Projects/youtube-transcriber && docker compose up -d
```

## Commands

### Transcribe a video

```bash
bash scripts/transcribe.sh "https://www.youtube.com/watch?v=VIDEO_ID"
```

Submits the video, polls until complete, and prints the full transcription JSON (text, segments with timestamps, language, word count).

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

Queries the database directly and shows a table of videos with their transcript/summary status.

### Get a transcription by video ID

```bash
curl -s http://localhost:8000/api/transcriptions/<video-uuid> | python3 -m json.tool
```

## Output format

Transcription JSON includes:
- `full_text` — complete transcript
- `segments[]` — timestamped chunks with `start`, `end`, `text`, `confidence`
- `language`, `word_count`, `model_size`, `processing_time_seconds`

## Notes

- Audio is downloaded via yt-dlp inside the worker container
- Whisper runs locally (default model: `base`, CPU)
- Summaries are generated via Claude Sonnet; long transcripts use chunk-then-consolidate
- Semantic search requires sentence-transformers (may not be installed in web container)
