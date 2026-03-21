# gstack Audit: youtube-transcriber
**Date:** 2026-03-21 | **Auditor:** Claude Sonnet 4.6 via gstack /retro + /review

---

## 1. What This Project Does

youtube-transcriber is a self-hosted YouTube transcription tool optimized for Apple Silicon. It accepts YouTube URLs (individual videos or entire channels), downloads audio via yt-dlp, transcribes using MLX Whisper (Metal GPU), runs speaker diarization via pyannote.audio, cleans up transcripts with Anthropic Haiku, generates summaries, and builds a semantic search index using nomic-embed-text-v1.5 (768d pgvector embeddings). The completed library supports both a web chat UI (ChatGPT-style RAG interface) and a Telegram bot for querying transcripts by natural language. It runs as a hybrid stack: Postgres + Redis + FastAPI web in Docker, with the Celery worker running natively on macOS for Metal GPU access.

---

## 2. /retro — Engineering Retrospective (30-day window: Feb 19 – Mar 21, 2026)

**Tweetable:** Mar 2–17: 73 commits (1 contributor, ~100% AI-assisted), 29k LOC added, 41% test ratio, 5 active days, peak 8pm local | Streak: 1d

### Summary Table

| Metric | Value |
|--------|-------|
| Commits to main (local) | 73 (67 pushed to origin) |
| Commits unpushed | 6 |
| Contributors | 1 (Kenneth / SentryClaw) |
| PRs merged | 0 (solo trunk-based dev) |
| Total insertions | 29,290 |
| Total deletions | 7,467 |
| Net LOC added | 21,823 |
| Test LOC (insertions) | 11,895 |
| Test LOC ratio | **40.6%** |
| Active days | 5 (Mar 2, 6, 7, 14, 17) |
| Detected sessions | 14 |
| Deep sessions (50+ min) | 4 |
| Avg session length | ~38 min |
| LOC / active hour | ~3,300 |
| AI-assisted commits | ~67 (100%, Co-Authored-By: Claude Opus 4.6) |
| Streak (team/personal) | **1 day** (last commit Mar 17) |

**First retro recorded — run again next week to see trends.**

### Contributor Leaderboard

```
Contributor           Commits   +/-                Top area
You (Kenneth)              73   +29,290/-7,467     app/services/ + tests/
```

This is a solo project. 100% of commits carry `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>` — effectively a human+AI pair programming engagement at extremely high throughput.

### Time & Session Patterns

```
Hour  Commits  ████████████████
 01:    2      ██
 09:    4      ████
 10:    2      ██
 11:    1      █
 12:    2      ██
 13:    5      █████
 14:    5      █████
 15:    4      ████
 16:    1      █
 17:    2      ██
 18:    4      ████
 19:    6      ██████
 20:   12      ████████████
 22:    5      █████
```

**Peak hour: 20:00 (8pm)** — the March 6 QA blitz drove the spike (12 commits in the 8pm hour alone, all test/fix cycles for chat backend). The pattern is broad-coverage, running 9am through 10pm with a clear evening concentration. No dead zone except early morning (2am-8am). Sessions span both daylight and night but the most productive deep work happened in the afternoon-evening block.

**Detected sessions (45-min gap threshold):**

| Date | Session | Duration | Type |
|------|---------|----------|------|
| Mar 2 | 09:18–09:19 | 2 min | Micro (init commit) |
| Mar 2 | 10:15–11:18 | 63 min | **Deep** |
| Mar 2 | 14:36–15:06 | 30 min | Medium |
| Mar 2 | 16:27–18:07 | 100 min | **Deep** |
| Mar 6 | 12:30–14:59 | 149 min | **Deep (2.5h marathon)** |
| Mar 6 | 15:19–15:44 | 25 min | Medium |
| Mar 6 | 18:12–18:46 | 34 min | Medium |
| Mar 6 | 19:22–20:46 | 84 min | **Deep** |
| Mar 6 | 22:02–22:31 | 29 min | Medium |
| Mar 7 | 01:35 | — | Micro (late-night fix) |
| Mar 7 | 12:34–12:38 | 4 min | Micro |
| Mar 14 | 01:38 | — | Micro (late-night) |
| Mar 14 | 09:08–09:15 | 7 min | Micro |
| Mar 17 | 18:09 | — | Micro |

Total active coding time: ~530 min (~8.8 hours). The March 6 day was a 10-hour marathon shipping all 4 chat phases in sequence.

### Shipping Velocity

```
feat:   11  (15%)  ███████████████
fix:    19  (26%)  ██████████████████████████
test:   14  (19%)  ███████████████████
docs:   11  (15%)  ███████████████
ci:      1  ( 1%)  █
other:  17  (23%)  ███████████████████████
```

*(Other = "Phase X:", "QA:", "Initial implementation" — uncategorized feat/test mix)*

Fix ratio at **26% is healthy** — well under the 50% warning threshold. The fix commits are clustered in two patterns: quick tactical fixes (model IDs, numpy type conversion, asyncpg syntax) and iterative QA-cycle fixes during the March 6 chat feature blitz. No evidence of fix-chains on the same subsystem indicating systemic bugs.

**PR size distribution** (estimated from LOC per commit): Most commits fall in Small/Medium range. Notable XL commits:
- Initial implementation: +4,117 (seed commit, expected)
- Rebuild frontend UI: +2,939 (design system overhaul)
- Phase 2 chat backend: +1,634 (new subsystem)
- Phase 3 chat UI: +1,283 (new subsystem)
- Phase 4 Telegram bot: +974 (new subsystem)

The Phase commits are each logically self-contained new subsystems, so the XL size is justified. The design system overhaul was also a single coherent refactor.

### Code Quality Signals

**Test ratio: 40.6%** — well above the 20% floor. This is genuinely impressive: 4 in every 10 LOC shipped is test code. Credit to the systematic QA-cycle pattern (each feature phase followed by multiple rounds of test writing and edge case coverage).

**Hotspot analysis (top 10 most-changed files):**

```
 33  docs/claude-diff-summary.md        (docs artifact, expected)
 32  docs/claude-test-results.txt       (docs artifact, expected)
 29  docs/claude-plan.md                (docs artifact, expected)
 12  tests/test_chat.py                 ⚠️  CHURN HOTSPOT
  9  README.md                          (docs, expected)
  8  app/templates/base.html            (UI iteration)
  8  app/config.py                      (config evolution)
  7  app/templates/partials/queue_content.html
  7  app/static/css/main.css
  7  app/services/search.py             (search feature evolution)
```

`tests/test_chat.py` at 12 changes is the only production-relevant churn hotspot. It went through 10+ QA rounds during the March 6 chat feature blitz — reflecting the complexity of testing async LLM-backed RAG correctly. The handoff docs (claude-plan, claude-diff-summary, claude-test-results) are expected to be high-churn artifacts given the CLAUDE.md workflow requirements.

### Test Health

- Total test files: 22 (covering all major subsystems)
- Tests added this period: effectively all 22 (project is 19 days old)
- Test LOC: 11,895 out of 29,290 total = **40.6%**
- Test pattern: systematic phase-by-phase QA rounds with dedicated test commits

Test files cover: alignment, API endpoints, channel filters, chat, chat toggle, config, design system, diarization, embedding service, feature smoke, filler removal, hybrid search, job retry, pipeline chain, process/email, search service, task orchestration, telegram bot, template filters, template rendering, transcript cleanup, transcription engine, V2 smoke, workflow integration, YouTube service.

**Gap:** Several test files exist for telegram bot but the actual handler flow (end-to-end message → RAG → reply) is not integration-tested with a real Telegram update.

### Focus & Highlights

**Focus score: ~65%** — the bulk of March 6's marathon session concentrated on `app/services/chat.py`, `app/routers/chat.py`, and `tests/test_chat.py`. Context-switching was minimal within sessions.

**Ship of the period:** The entire "Chat with Transcripts" feature — 4 phases shipped in a single 10-hour day (March 6):
1. Phase 1: Chat toggle system (DB + API + search filter + UI) — +578 LOC
2. Phase 2: RAG chat backend (sessions, embedding search, Anthropic integration) — +1,634 LOC
3. Phase 3: ChatGPT-style web UI — +1,283 LOC
4. Phase 4: Telegram bot — +974 LOC

Total: ~4,469 LOC of new feature across 4 coherent layers in one sitting. That is genuinely remarkable throughput even accounting for AI assistance.

### Your Week

**What you did well:**
1. **Systematic phase-by-phase delivery** — each feature shipped as a numbered phase with docs + tests + QA, not a big-bang merge. The chat feature could have been one monolithic commit; instead it's 4 independently testable layers.
2. **40.6% test ratio** — you didn't skip test coverage to ship faster. Every major feature phase was followed by dedicated QA rounds.
3. **Rapid diagnosis and fix of operational issues** — the March 6-7 late-night fix sequence (asyncpg CAST syntax, einops missing dep, 409 Telegram conflict) shows strong operational instincts: the project went live and you iterated quickly on real failure modes.

**Where to level up:**
1. **Push the 6 unpushed local commits to origin** — channel filtering and classification changes exist only locally. If the Mac mini dies tonight, they're gone.
2. **Break the 2-week commit gap** — there have been 14 days since the last commit (Mar 17 → Mar 21). This project is production infrastructure; even small maintenance touches (dependency updates, stale job cleanup improvements) keep the flywheel moving.

### Top 3 Team Wins

1. **Chat with Transcripts (4 phases, 1 day)** — A full RAG chat stack from DB schema through to Telegram bot in a single marathon session. Rare velocity.
2. **Hybrid search (BM25 + pgvector RRF)** — Production-grade reciprocal rank fusion replacing naive vector-only search. Significantly better recall for short/keyword queries.
3. **nomic-embed-text-v1.5 upgrade with speaker-aware chunking** — Moving from basic to speaker-boundary-aware chunks with 768d embeddings is a meaningful quality improvement for multi-speaker content.

### 3 Things to Improve

1. **Push the unpushed commits** — 6 local commits including channel classification are at risk.
2. **Add worker health monitoring** — the native Celery worker crashes silently; jobs queue forever. Even a simple heartbeat check would help.
3. **Add rate limiting to LLM endpoints** — both the chat API and Telegram bot accept unlimited queries. One runaway session could drive significant API cost.

### 3 Habits for Next Week

1. `git push origin main` at the end of every session (< 30 seconds, protects your work).
2. Add a 1-line cron health check: `celery -A app.tasks.celery_app inspect ping -t 5` and alert on failure.
3. Before any new feature, check if there's an existing test that exercises the happy path — use that as your regression anchor for the feature's entry point.

---

## 3. /review — Security & Reliability Findings

> Scope: all modified files + critical path code. Focus: API security, Celery reliability, hybrid architecture failure modes, DB/pgvector query correctness, Telegram bot surface, LLM error handling, test coverage gaps.

### CRITICAL

#### C1 — No authentication on any API route
**File:** `app/main.py`, all `app/routers/*.py`

Every API endpoint is completely unauthenticated. `POST /api/videos`, `POST /api/channels`, `DELETE /api/chat/sessions/{id}`, `POST /api/jobs/{id}/retry` — all open. For a local-only tool this may be intentional, but:
- The web service binds to `0.0.0.0:8000` (from docker-compose `ports: "8000:8000"`), making it reachable on the local network
- Any device on the same WiFi can submit unlimited transcription jobs, delete chat sessions, or trigger pipeline retries
- The Telegram bot has an allowlist (`telegram_allowed_users`) but the web API has nothing equivalent

**Impact:** Accidental or malicious abuse of the transcription pipeline, Anthropic API cost inflation, data deletion.

**Fix:** At minimum, add HTTP Basic Auth middleware or an API key header check. FastAPI's `HTTPBasicCredentials` takes <20 lines.

---

#### C2 — Unbounded memory load for large chat sessions
**File:** `app/routers/chat.py:96`, `app/telegram_bot.py:handle_message`

Both the web `send_message` handler and the Telegram `handle_message` handler do:
```python
.options(selectinload(ChatSession.messages))
```
...before trimming to `chat_max_history` (default: 10 pairs). If a session accumulates 1,000+ messages (plausible over months of daily use), the entire message history is loaded into memory on every single query before being sliced down to 20 items. This will eventually OOM the web process or the bot.

**Impact:** Memory exhaustion after prolonged use. Silent OOM kills in Docker with no log.

**Fix:** Add `LIMIT` to the message query: load only the last `chat_max_history * 2` messages from the DB rather than loading all and slicing in Python.

---

### HIGH

#### H1 — Native Celery worker failure is invisible
**Files:** `docker-compose.yml`, `app/tasks/celery_app.py`

The Celery worker runs natively outside Docker with no health monitoring. When it crashes:
- Jobs enter "running" state (via `task_acks_late=True` + `task_track_started=True`) and never complete
- The stale job reaper (`app/tasks/cleanup.py`) catches tasks after a timeout, but only if `cleanup` is scheduled
- There is no worker heartbeat check, no alerting, no auto-restart

The `scripts/start_telegram_bot.sh` and `scripts/start_worker.sh` scripts start the processes but offer no restart-on-failure. A Mac sleep/wake cycle or transient crash leaves the queue draining silently.

**Impact:** At 2am, a video submitted before bed has been "processing" for 8 hours. No one knows.

**Fix:** Use launchd plist with `KeepAlive=true` for the worker process (a plist already exists: `com.sentryclaw.yt-worker.plist` — verify it has `KeepAlive`). Add a cron that pings `celery inspect ping` and posts to Telegram on failure.

---

#### H2 — No retry for Anthropic rate limit errors (429)
**Files:** `app/services/chat.py:chat_with_context`, `app/services/summarization.py`

Both the chat service and summarization service wrap Anthropic API calls in bare `except Exception` handlers with no retry logic. A 429 rate limit error from Anthropic returns "Sorry, an error occurred" to the user immediately. Anthropic rate limits are transient and usually resolve in 60 seconds.

**Impact:** Chat becomes unusable during moderate API load; summarization fails silently (falls back to empty summary or raises to the Celery task which retries, but with the wrong error message).

**Fix:** Use `anthropic.RateLimitError` catch + exponential backoff (2-3 retries). The `tenacity` library would handle this in <10 lines.

---

#### H3 — Embedding string injected into raw SQL
**File:** `app/services/search.py:_vector_search`, `_hybrid_search`

```python
embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
# ...
sql = f"""... CAST(:embedding AS vector) ..."""
params.update({"embedding": embedding_str, ...})
```

The embedding vector is built via string concatenation and passed as a parameterized value — fine for now. However, the `{where}` clause and `{"AND" if where else "WHERE"}` are injected directly into the f-string SQL. While `_build_where_clause` currently only accepts a UUID and a bool (both safe), this pattern is fragile. If `_build_where_clause` ever accepts a user-supplied string, it becomes an injection point without any obvious warning at the call site.

More immediately: the `LIMIT {candidate_limit}` literal embedding is safe (integer), but mixing parameterized and f-string SQL in the same query body is a pattern that will eventually cause a mistake.

**Impact:** Current code is safe but the pattern will catch developers off guard. One refactor away from injection.

**Fix:** Use `sqlalchemy.text()` with exclusively parameterized values, or move to SQLAlchemy Core/ORM for all search queries.

---

#### H4 — No cost controls on LLM usage
**Files:** `app/services/chat.py`, `app/services/summarization.py`, `app/tasks/cleanup.py`

There are no per-session, per-user, or daily Anthropic API spend limits. The chat endpoint accepts messages up to 100,000 characters (`max_length=100_000` in `ChatMessageSend`), and the token truncation in `chat_with_context` uses a rough `chars // 4` approximation. For a 100k character message with 10k token retrieved context, the actual prompt could exceed 150k tokens (Claude's cap) before the truncation guard triggers — and the approximation error could mean it doesn't trigger at all.

**Impact:** A single chat message could cost $5-15 in tokens; daily use without limits could rack up uncontrolled Anthropic costs.

**Fix:** Add a daily/hourly token budget check using the `prompt_tokens` + `completion_tokens` fields already being stored in `ChatMessage`. Alert via Telegram when daily spend exceeds a threshold.

---

### MEDIUM

#### M1 — Chat session message history grows unbounded (DB layer)
**File:** `app/models/chat_session.py` (inferred from ORM)

There is no maximum message count per session, no session expiry, and no archival mechanism. Over months of daily use, sessions accumulate indefinitely in PostgreSQL. The `list_sessions` endpoint paginates (good), but there's no cleanup job.

**Fix:** Add a `max_messages_per_session` config and a periodic cleanup task that archives or truncates old sessions.

---

#### M2 — Telegram bot uses unbounded DB engine
**File:** `app/telegram_bot.py:28-29`

```python
_engine = create_async_engine(settings.database_url_native, echo=False)
_async_session = async_sessionmaker(_engine, expire_on_commit=False)
```

No connection pool size is set. Default asyncpg pool is 5-10 connections. Under concurrent Telegram messages (e.g., two users chatting simultaneously), this is fine. But if polling receives a burst of messages, each `await _get_db()` creates a new session from the shared pool, and concurrent handlers could exhaust it.

**Fix:** Set `pool_size=5, max_overflow=5` on the engine explicitly. For a personal bot this is plenty.

---

#### M3 — `trust_remote_code=True` in SentenceTransformer
**Files:** `app/services/embedding.py:19`, `app/services/search.py:19`

```python
SentenceTransformer(settings.embedding_model, ..., trust_remote_code=True)
```

`trust_remote_code=True` executes arbitrary Python from the HuggingFace model repo at load time. This is required for nomic-embed-text-v1.5 but means a compromised or malicious model update could run arbitrary code in the worker process.

**Impact:** Low probability but high blast radius — worker has access to DB, filesystem, and network.

**Fix:** Pin the model revision hash in the `SentenceTransformer()` call: `revision="<commit_hash>"`. This prevents silent model updates from being picked up automatically.

---

#### M4 — Cleanup task has no max_retries and silently swallows errors
**File:** `app/tasks/cleanup.py:cleanup_transcript_task`

```python
@celery.task(bind=True, name="tasks.cleanup_transcript")  # no max_retries
def cleanup_transcript_task(self, video_id: str) -> str:
    ...
    except Exception as exc:
        # Don't fail the pipeline on cleanup errors — log and continue
        return video_id  # silently continues
```

The design choice to continue on cleanup failure is defensible (cleanup is optional). But logging `error()` and returning normally means the Celery task shows as `SUCCESS` even when LLM cleanup failed. Monitoring dashboards (if added later) would show 100% success rate even during repeated LLM outages.

**Fix:** Emit a `cleanup_failed` metric/event that can be monitored separately from task success/failure.

---

#### M5 — The hybrid search SQL has f-string / parameterized mixing
**File:** `app/services/search.py:_hybrid_search`

The hybrid search query embeds `{candidate_limit}` and `{where}` as f-string interpolations alongside `:embedding`, `:query`, and `:limit` parameterized values. The query also double-uses `{where}` (once in each CTE), which means any future WHERE clause change must be applied consistently in two places.

**Fix:** Extract the CTEs into separate named queries or use SQLAlchemy Core. At minimum, add a comment warning that `{where}` appears twice.

---

### LOW / INFORMATIONAL

#### L1 — Hardcoded default credentials
**File:** `app/config.py:6-8`

```python
database_url: str = "postgresql+asyncpg://transcriber:transcriber@..."
```

Credentials are in the default string. If `.env` is missing, the app starts with predictable credentials. For a network-accessible service (see C1), this is a compounding risk.

**Fix:** Set `database_url` default to `""` and fail at startup with a clear error if not configured.

---

#### L2 — No CORS configuration
**File:** `app/main.py`

FastAPI's default is no CORS headers. If anyone ever tries to access the API from a browser at a different origin (e.g., a mobile app, a cross-origin admin tool), all requests will fail silently with CORS errors.

**Fix:** Add `CORSMiddleware` with an explicit allowlist, even if just `["http://localhost:8000"]`.

---

#### L3 — No request size limit
**File:** `app/main.py`

FastAPI/uvicorn has no configured request body size limit. While the `ChatMessageSend` schema limits content to 100k characters, multipart uploads or other endpoints have no cap.

---

#### L4 — `summarize_text` raises ValueError for missing API key
**File:** `app/services/summarization.py:36`

```python
if not api_key:
    raise ValueError("ANTHROPIC_API_KEY is required for summarization")
```

This `ValueError` propagates up to the Celery task which will mark it as `FAILURE` and retry. The retry is wasteful since the API key won't appear between retries. The cleanup task handles this more gracefully (skips with a warning). Summarization should do the same.

---

#### L5 — Audio files accumulate with no cleanup
**File:** `app/tasks/download.py`, `docker-compose.yml`

Downloaded audio files are stored in `/data/audio` (Docker volume) and never deleted after transcription completes. For heavy channel processing (hundreds of videos), this volume will grow without bound.

**Fix:** Delete the audio file after the transcription task completes successfully. Add this as a step in `app/tasks/transcribe.py` or as a post-pipeline cleanup.

---

### Test Coverage Gaps vs Critical Paths

| Critical Path | Coverage Status |
|---------------|----------------|
| Submit video → queue pipeline → complete | `test_workflow_integration.py` — partial |
| Chat message → RAG search → LLM response | `test_chat.py` — unit tested, no e2e |
| Telegram message → handler → reply | `test_telegram_bot.py` — unit tested, no handler e2e |
| Hybrid search correctness (RRF ranking) | `test_hybrid_search.py` — present |
| Anthropic 429 / rate limit handling | **NOT TESTED** |
| Worker crash → stale job detection | **NOT TESTED** |
| Chat session overflow (1000+ messages) | **NOT TESTED** |
| Channel batch completion | `test_pipeline_chain.py` — partial |
| API unauthenticated access | **NOT TESTED** (no auth to test) |

---

## 4. Improvement Opportunities — What Breaks Silently

The following analysis focuses on what would hurt most at 2am.

### Silent failure #1: Worker goes down, nothing tells you

The native Celery worker is the most critical single point of failure. When it dies (Mac sleep, OOM, exception in task), the behavior is:
- New job submissions: queued to Redis, sit there forever
- In-flight jobs: marked "running" forever (or until stale reaper fires)
- User experience: the progress bar spins indefinitely
- You find out: when you check the dashboard the next morning

**What would help:** A launchd plist with `KeepAlive=true` (already exists — verify it's active). A Telegram alert from a cron that runs `celery inspect ping -t 5 2>&1 | grep -q "pong" || telegram_alert "Worker is down"`. Total implementation: 15 minutes.

### Silent failure #2: Anthropic API outage during summarization

If Anthropic's API is down during the summarization step:
- The task retries twice (2x max_retries with backoff)
- After both retries fail, the video is marked `failed`
- The pipeline is dead — embedding never runs, the video is unsearchable
- You find out: when you notice the video isn't in search results

The LLM cleanup step handles this better (silently skips and continues). Summarization could do the same — or at minimum, if summarization fails, the pipeline should continue to the embedding step so the transcript is at least searchable.

**What would help:** Wrap summarization failure in a "continue without summary" path, same as cleanup. Retry with exponential backoff on 429s using `tenacity`. Low effort, high resilience.

### Silent failure #3: Embedding model OOM on large videos

Long videos (3+ hour conference talks) produce many transcript segments. The embedding task loads all segments, builds chunks, calls the sentence-transformer model for each batch, and writes to DB. If the model runs out of Metal GPU memory mid-batch, the task fails and re-runs from scratch (deleting existing chunks first via `db.query(EmbeddingChunk).filter(...).delete()`).

The idempotent design (delete-before-write) is correct but means a 2-hour embedding job that fails at 90% starts over. No progress checkpointing.

**What would help:** Batch commit chunks in groups of 100 rather than accumulating all then committing. If the task fails mid-way, only the already-committed chunks get deleted on retry — but the task as written deletes all first anyway. More realistically: add chunk count logging so you can see progress, and alert if the task takes >30 minutes.

### Silent failure #4: DB connection exhaustion

The web process (asyncpg) and the Celery worker (psycopg2 sync engine) each maintain separate connection pools to PostgreSQL. The Telegram bot opens a third engine. No explicit pool limits are set on the bot engine. If all three run simultaneously with concurrent requests, PostgreSQL's `max_connections` (default 100) could be approached with heavy load.

For personal use this isn't a real problem today. But it's worth documenting so it doesn't surprise you when you add more consumers.

### Silent failure #5: Audio volume fills up

Downloaded audio is never cleaned up. At roughly 50-150MB per hour of video, processing 100 long videos fills the audio volume with 5-15GB of audio that's no longer needed. Docker volumes don't shrink automatically. You find out when `docker stats` shows the host disk at 98%.

**What would help:** Delete audio after transcription: `os.unlink(video.audio_file_path)` in the transcription task after success. One line.

### What would genuinely hurt at 2am

Ranked by pain:
1. **Worker down + no alert** — job you submitted at midnight is still "running" at 8am. Had a meeting with this content.
2. **Anthropic API outage during a batch channel sync** — 50 videos fail at the summarization step, none searchable.
3. **Chat session memory leak** — after 6 months of daily use, the web process OOMs silently under a Docker restart loop.
4. **Audio disk full** — Docker crashes, postgres volume potentially corrupt if OOM kills happen during write.
5. **PostgreSQL credentials in default config** — only matters if the port is accidentally exposed, but compound risk with the open API.

---

## 5. Skill Ratings (1–10)

### Architecture: 8/10
The hybrid native-worker + Docker-infra design is well-reasoned for Apple Silicon. The separation of concerns (FastAPI web ↔ Celery tasks via Redis ↔ PostgreSQL + pgvector) is clean and production-appropriate. Using `chain()` for pipeline steps rather than monolithic tasks is the right call. The decision to use `task_acks_late=True` + `worker_prefetch_multiplier=1` shows awareness of Celery reliability concerns. The main gap is the lack of worker health monitoring and the unbounded audio/chat session accumulation.

**What would make it a 10:** Worker heartbeat monitoring, dead-letter queue visibility, audio cleanup, and documented failure modes for each pipeline step.

### Code Quality: 7/10
The code is clean, typed, and well-structured. SQLAlchemy models are properly layered, Pydantic schemas handle validation, and structlog is used consistently. The main concerns: f-string SQL mixing, `trust_remote_code=True` without pinned revision, and the `chars//4` token approximation. The session message loading pattern (load all, slice in Python) will scale poorly. No authentication is a significant omission even for personal use.

**What would make it a 10:** Parameterized SQL throughout, model revision pinning, proper token counting (tiktoken) for context management, API key middleware.

### Test Coverage: 8/10
40.6% test LOC ratio is exceptional for a project of this velocity. 22 test files covering all major subsystems. The QA-cycle approach (feature → test rounds → QA commit) produces real coverage rather than checkbox tests. The gaps are meaningful though: no e2e integration test for the full pipeline, no rate limit error path testing, no load testing for session overflow.

**What would make it a 10:** E2e test that submits a video and asserts it ends up searchable. Rate limit mock tests. Session overflow test.

### Shipping Velocity: 10/10
73 commits in 5 active days. A complete RAG chat stack from zero to Telegram bot in one session. Hybrid search, speaker-aware chunking, and embedding model upgrade all in the same day. The AI-assisted workflow (100% Claude co-authored) is operating at maximum efficiency — no wasted motion, coherent phase structure, high test ratio maintained under velocity pressure. This is what the "boil the lake" principle looks like in practice.

### Operational Readiness: 5/10
The project runs well when everything works, but has multiple silent failure modes with no recovery path. No worker health monitoring, no alerting, no cost controls, no cleanup jobs, no auth. For a personal tool used daily, these gaps are manageable — but they represent real 2am risks. The stale job reaper and idempotent task design show operational awareness; the execution just needs to be completed.

**What would make it a 10:** Worker heartbeat + Telegram alert, audio cleanup task, daily cost budget check, session archival, API key middleware.

---

## Appendix: Modified Files (Not Yet Pushed)

The following files are modified locally but not on origin/main:

```
M  app/routers/transcriptions.py
M  app/services/chat.py
M  app/services/embedding.py
M  app/tasks/embed.py
M  app/telegram_bot.py
M  docker-compose.yml
M  scripts/reembed_all.py
M  scripts/rotate_logs.sh
M  scripts/start_telegram_bot.sh
M  tests/test_chat.py
M  tests/test_embedding_service.py
M  tests/test_telegram_bot.py
?? docs/PLAN.md
```

Plus 6 unpushed commits (channel video filtering + classification). **Push these before any hardware work.**

---

*Report generated by Claude Sonnet 4.6 via gstack /retro + /review | 2026-03-21*
