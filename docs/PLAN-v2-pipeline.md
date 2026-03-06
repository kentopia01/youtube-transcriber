# Plan: V2 Transcription Pipeline

## Status: IMPLEMENTED — All 5 phases complete (0-4)

---

## Goal

Upgrade the transcription pipeline to use Apple Silicon-native MLX inference, language-aware routing, speaker diarization, and LLM-powered transcript cleanup.

## Current Pipeline
```
YouTube URL → yt-dlp (download WAV) → faster-whisper base (CPU, Docker) → Claude Sonnet (summarize) → MiniLM (embed)
```

## Proposed Pipeline
```
YouTube URL (yt-dlp, native)
  ↓
Language Detection (mlx-whisper tiny, first 30s, negligible cost)
  ↓
Transcription (mlx-whisper large-v3-turbo, Apple Silicon Metal)
  ↓
Speaker Diarization (pyannote.audio, CPU)
  ↓
Forced Alignment + Speaker Merge (whisperX)
  ↓
LLM Transcript Cleanup (Anthropic Haiku/Sonnet)
  ↓
Summarize (Anthropic Sonnet) → Embed (MiniLM, native)
```

---

## Architecture Change: Native macOS Worker

### Why native instead of Docker?

MLX (Apple's ML framework) runs natively on Apple Silicon via Metal — it cannot run inside Docker. Docker on macOS uses a Linux VM, which has no access to Metal/MPS. To use MLX-accelerated transcription, the Celery worker must run **natively on macOS**.

### Hybrid architecture

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

- **Postgres, Redis, Web (FastAPI):** remain in Docker — no changes needed
- **Worker:** moves from Docker to native macOS process (venv or system Python)
- Worker connects to Postgres/Redis via `localhost` (Docker ports already exposed)

### Worker management

The native worker will be managed via **launchd** (like other persistent services on the Mac mini):

- Plist: `~/Library/LaunchAgents/com.sentryclaw.yt-worker.plist`
- Logs: `/tmp/yt-worker/yt-worker.log`
- Restart: `launchctl kickstart -k gui/$(id -u)/com.sentryclaw.yt-worker`

---

## Implementation Phases

### Phase 0: Native Worker Migration
**Scope:** Move the Celery worker from Docker to native macOS, replace faster-whisper with mlx-whisper

**Changes:**

#### Native Python environment
- Create venv at `~/Projects/youtube-transcriber/.venv-native`
- Install: `mlx-whisper`, `pyannote.audio`, `whisperx`, `celery`, `sqlalchemy`, `psycopg2-binary`, `anthropic`, `sentence-transformers`, `tiktoken`, `yt-dlp`, `structlog`
- Python 3.12+ (already on the system)

#### Config changes
- `app/config.py`:
  - Add `worker_mode: str = "native"` (native | docker)
  - Change DB/Redis defaults to use `localhost` when native:
    - `database_url_sync` → `postgresql+psycopg2://transcriber:transcriber@localhost:5432/transcriber`
    - `redis_url` → `redis://localhost:6379/0`
  - Add `audio_dir: str = "./data/audio"` (local path instead of `/data/audio`)
  - Add `model_cache_dir: str = "./data/models"` (local path instead of `/data/models`)
- `.env.native` (new file):
  - Native worker env with localhost URLs and local paths
- `docker-compose.yml`:
  - Remove `worker` and `flower` services (optional — can keep for Docker-only deployments)
  - Keep `postgres`, `redis`, `web`

#### Transcription engine swap
- `app/services/transcription.py`:
  - Replace `faster_whisper` imports with `mlx_whisper`
  - `mlx_whisper.transcribe()` API is similar but returns slightly different structure
  - Adapter function to normalize output format
  - Remove `_get_model()` singleton cache (mlx-whisper handles caching internally)
  - Default model: `mlx-community/whisper-large-v3-turbo`

#### Worker startup script
- `scripts/start_worker.sh`:
  ```bash
  #!/usr/bin/env bash
  cd ~/Projects/youtube-transcriber
  source .venv-native/bin/activate
  export $(grep -v '^#' .env.native | xargs)
  celery -A app.tasks.celery_app worker --loglevel=info --concurrency=1
  ```
  - Concurrency=1 because MLX uses Metal GPU — parallel workers would compete for the same GPU

#### launchd plist
- `com.sentryclaw.yt-worker.plist` installed to `~/Library/LaunchAgents/`

#### Data directories
- `mkdir -p ~/Projects/youtube-transcriber/data/{audio,models}`
- Audio and model caches stored locally (not in Docker volumes)

**Risk:** Two env files (`.env` for Docker, `.env.native` for worker) adds config surface. Mitigate by documenting clearly and validating on startup.

---

### Phase 1: Language Detection
**Scope:** Add language detection using mlx-whisper before full transcription

**Changes:**
- `app/services/transcription.py`:
  - New function `detect_language(audio_path: str) -> str`:
    - Uses `mlx_whisper.transcribe()` with `mlx-community/whisper-tiny` on first 30s
    - Extracts detected language from result
    - Tiny model is ~40MB, runs in <1s — negligible overhead
  - Main `transcribe_audio()` function calls `detect_language()` first
  - Passes detected language to the main transcription call (avoids Whisper re-detecting)
  - Language stored in transcription record (existing `language` column)
- `app/config.py`:
  - Add `whisper_language: str = "auto"` (auto = detect, or force e.g. "en")
  - Add `whisper_model: str = "mlx-community/whisper-large-v3-turbo"` (replaces `whisper_model_size`)
  - Add `whisper_detect_model: str = "mlx-community/whisper-tiny"` (for language probe)
- `.env.native` / `.env.example`:
  - Add `WHISPER_MODEL`, `WHISPER_DETECT_MODEL`, `WHISPER_LANGUAGE`

**Note:** Since both English and non-English use the same model (large-v3-turbo handles 99 languages well), the language detection is primarily for:
1. Storing metadata (what language was detected)
2. Passing to Whisper to skip auto-detection overhead on the full file
3. Future: routing to a specialized engine (e.g., Canary-Qwen for English if NVIDIA GPU becomes available)

---

### Phase 2: Speaker Diarization
**Scope:** Add pyannote.audio diarization + whisperX alignment for speaker-labeled transcripts

**Dependencies:**
- Hugging Face access token (for `pyannote/speaker-diarization-community-1` model)
- User must accept HF model agreement at https://huggingface.co/pyannote/speaker-diarization-community-1

**Changes:**

#### New service: diarization
- `app/services/diarization.py`:
  - `diarize(audio_path: str, hf_token: str, num_speakers: int | None = None) -> list[dict]`
  - Uses `pyannote.audio.Pipeline.from_pretrained("pyannote/speaker-diarization-community-1")`
  - Runs on CPU (pyannote supports CPU, no CUDA required)
  - Returns: `[{"start": float, "end": float, "speaker": "SPEAKER_00"}, ...]`
  - Optional `num_speakers` hint for known speaker count

#### New service: alignment + merge
- `app/services/alignment.py`:
  - `align_and_merge(audio_path, transcript_segments, diarization_segments, language) -> list[dict]`
  - Uses whisperX for forced alignment (word-level timestamps)
  - Maps each word/segment to the overlapping diarization speaker
  - Merge strategy: majority-vote — assign segment to the speaker who covers the most time in that segment
  - Output: `[{"start", "end", "text", "speaker", "confidence"}, ...]`

#### DB migration
- Alembic migration: add `speaker VARCHAR(32)` column to `transcription_segments` table (nullable)

#### Pipeline integration
- New file `app/tasks/diarize.py`:
  - Celery task `tasks.diarize_and_align`
  - Loads audio + existing transcription segments from DB
  - Runs diarization → alignment → updates segment records with speaker labels
  - Updates job progress: 50% → 65%
- `app/tasks/pipeline.py`:
  - New chain: `download → transcribe → diarize_and_align → cleanup → summarize → embed`
  - Diarization step skipped if `DIARIZATION_ENABLED=false`

#### Config
- `app/config.py`:
  - Add `hf_token: str = ""`
  - Add `diarization_enabled: bool = True`
- `.env.native` / `.env.example`:
  - Add `HF_TOKEN=`, `DIARIZATION_ENABLED=true`

#### API output
- `app/routers/transcriptions.py`:
  - Include `speaker` field in each segment
  - Add `speakers: list[str]` summary to response (unique speaker list)

**Performance on CPU:** pyannote diarization runs at ~0.3-0.5x realtime on CPU. A 10-min video takes ~20-30 min for diarization. Combined with transcription, total pipeline ~25-40 min for a 10-min video. Acceptable for async processing.

---

### Phase 3: LLM Transcript Cleanup
**Scope:** Replace regex filler-word removal with LLM-powered cleanup

**Changes:**

#### New service: transcript cleanup
- `app/services/transcript_cleanup.py`:
  - `clean_transcript(segments: list[dict], api_key: str, model: str) -> list[dict]`
  - **Chunking strategy:**
    - Short transcripts (< 4000 words): single Haiku call
    - Long transcripts: chunk into ~2000-word blocks, 200-word overlap, clean each, stitch
  - **Prompt design:**
    ```
    Clean this transcript for readability. Rules:
    - Remove filler words (um, uh, like, you know, I mean, basically, sort of, kind of)
    - Fix obvious grammar and punctuation errors
    - Preserve speaker labels exactly (e.g., [SPEAKER_00])
    - Do NOT change meaning, rephrase, or add content
    - Do NOT remove technical terms, proper nouns, or intentional repetition
    - Return the cleaned text only, no commentary
    ```
  - Returns cleaned segments preserving original structure (timestamps, speaker labels)

#### Remove old regex cleanup
- `app/services/transcription.py`:
  - Remove `clean_filler_words()` function entirely
  - Raw transcript stored as-is; cleanup happens as separate pipeline step

#### Pipeline integration
- New file `app/tasks/cleanup.py`:
  - Celery task `tasks.cleanup_transcript`
  - Reads transcription from DB
  - Sends through LLM cleanup
  - Updates `full_text` + individual segment text in DB
  - Updates job progress: 65% → 75%
- `app/tasks/pipeline.py`:
  - Chain: `download → transcribe → diarize_and_align → cleanup → summarize → embed`
  - Cleanup step skipped if `TRANSCRIPT_CLEANUP_ENABLED=false`

#### Config
- `app/config.py`:
  - Add `transcript_cleanup_enabled: bool = True`
  - Add `cleanup_model: str = "claude-haiku-4-20250514"`
- `.env.native` / `.env.example`:
  - Add `TRANSCRIPT_CLEANUP_ENABLED=true`, `CLEANUP_MODEL=claude-haiku-4-20250514`

**Cost estimate:** Haiku at ~$0.25/M input + $1.25/M output tokens. Typical 5000-word transcript ≈ 7k tokens input ≈ $0.002/video. At 100 videos/month ≈ $0.20/month. Negligible.

---

### Phase 4: Output Format + Skill Updates
**Scope:** Update API responses and OpenClaw skills for new features

**Changes:**

#### API output
- `app/routers/transcriptions.py`:
  - Response now includes:
    - `language_detected: str`
    - `speakers: list[str]` (unique speaker list)
    - `segments[].speaker: str | null`
    - `cleanup_model: str | null` (which LLM cleaned it)
    - `diarization_enabled: bool`

#### Skill: yt-transcribe
- `skills/yt-transcribe/scripts/transcribe.sh`:
  - Display detected language in output
  - Show speaker count when diarization is enabled
- `skills/yt-transcribe/SKILL.md`:
  - Document new features

#### Skill: yt-chat
- `skills/yt-chat/scripts/chat.py`:
  - Update `build_context()` to format speaker-labeled transcript:
    ```
    [SPEAKER_00] 0:00 - 0:15: Welcome to the show...
    [SPEAKER_01] 0:15 - 0:32: Thanks for having me...
    ```
  - Enables queries like "what did Speaker 1 say about X?"
  - Add `--speakers` flag to show speaker summary
- `skills/yt-chat/SKILL.md`:
  - Document speaker-aware queries

#### README
- Update project README with:
  - New pipeline diagram
  - Native worker setup instructions
  - New env vars
  - Performance expectations

---

## Environment Variables Summary

| Variable | Default | Phase | Purpose |
|---|---|---|---|
| `WORKER_MODE` | `native` | 0 | native or docker |
| `WHISPER_MODEL` | `mlx-community/whisper-large-v3-turbo` | 0 | MLX whisper model |
| `WHISPER_DETECT_MODEL` | `mlx-community/whisper-tiny` | 1 | Language detection model |
| `WHISPER_LANGUAGE` | `auto` | 1 | Force language or auto-detect |
| `HF_TOKEN` | — | 2 | HuggingFace token for pyannote |
| `DIARIZATION_ENABLED` | `true` | 2 | Toggle speaker diarization |
| `TRANSCRIPT_CLEANUP_ENABLED` | `true` | 3 | Toggle LLM cleanup |
| `CLEANUP_MODEL` | `claude-haiku-4-20250514` | 3 | Model for transcript cleanup |

## DB Migrations

1. Add `speaker VARCHAR(32)` to `transcription_segments` table (Phase 2)

## New Files

| File | Phase | Purpose |
|---|---|---|
| `.env.native` | 0 | Native worker environment config |
| `scripts/start_worker.sh` | 0 | Worker startup script |
| `com.sentryclaw.yt-worker.plist` | 0 | launchd service definition |
| `app/services/diarization.py` | 2 | pyannote speaker diarization |
| `app/services/alignment.py` | 2 | whisperX alignment + speaker merge |
| `app/services/transcript_cleanup.py` | 3 | LLM-powered transcript cleanup |
| `app/tasks/diarize.py` | 2 | Celery diarization task |
| `app/tasks/cleanup.py` | 3 | Celery cleanup task |

## Dependencies (native worker venv)

| Package | Phase | Purpose |
|---|---|---|
| `mlx-whisper` | 0 | Apple Silicon-native Whisper via MLX/Metal |
| `pyannote.audio` | 2 | Speaker diarization |
| `whisperx` | 2 | Forced alignment + speaker merge |
| `celery[redis]` | 0 | Task queue (already used) |
| `sqlalchemy` + `psycopg2-binary` | 0 | DB access (already used) |
| `anthropic` | 3 | LLM API calls |
| `sentence-transformers` | 0 | Embedding generation (already used) |
| `tiktoken` | 0 | Token counting (already used) |
| `yt-dlp` | 0 | YouTube download (already used) |
| `structlog` | 0 | Logging (already used) |

## Performance Expectations

| Scenario | Current (base, CPU, Docker) | V2 (large-v3-turbo, MLX Metal, full pipeline) |
|---|---|---|
| 10-min video | ~3-5 min | ~5-10 min |
| 30-min video | ~8-15 min | ~15-25 min |
| 1-hour video | ~15-30 min | ~30-50 min |

MLX on Apple Silicon is dramatically faster than faster-whisper on CPU. The `large-v3-turbo` model is ~4x faster than `large-v3` at near-identical accuracy. Diarization (CPU) adds ~1x realtime overhead. LLM cleanup adds ~10-15s per video. Net result: **better quality at comparable or faster speed**.

## Pluggable Engine Design

The transcription service uses a strategy pattern for future extensibility:

```python
class TranscriptionEngine(Protocol):
    def detect_language(self, audio_path: str) -> str: ...
    def transcribe(self, audio_path: str, language: str | None) -> TranscriptResult: ...

class MLXWhisperEngine(TranscriptionEngine): ...       # Current: Apple Silicon via Metal
class FasterWhisperEngine(TranscriptionEngine): ...    # Fallback: CPU via CTranslate2
class CanaryQwenEngine(TranscriptionEngine): ...       # Future: NVIDIA GPU via NeMo
```

Engine selection via `TRANSCRIPTION_ENGINE` env var. Default: `mlx` on macOS, `faster-whisper` on Linux.

---

## Execution Order

1. **Phase 0** — Native worker migration + mlx-whisper swap (foundation)
2. **Phase 1** — Language detection (quick win, enables smart routing)
3. **Phase 2** — Speaker diarization (biggest quality improvement)
4. **Phase 3** — LLM transcript cleanup (polish)
5. **Phase 4** — Output format + skill updates (user-facing changes)

Estimated total effort: ~4-6 hours of coding agent work across all phases.

---

## Future: Canary-Qwen-2.5B Integration

When NVIDIA GPU hardware becomes available (cloud VM, dedicated server, or eGPU):

1. Implement `CanaryQwenEngine` using NeMo SALM
2. Set `TRANSCRIPTION_ENGINE=canary-qwen` on that machine
3. Route English audio to Canary-Qwen (WER 5.63% vs large-v3-turbo ~7-8%)
4. Keep mlx-whisper as fallback for non-English and local processing

No pipeline changes needed — just a new engine class and env var.
