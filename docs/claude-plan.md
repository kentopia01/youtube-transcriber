# Claude Plan — Autonomous proactive direction (2026-04-18)

Status: **proposed, awaiting go-ahead.** This plan replaces ad-hoc feature work with a deliberate pivot: the system becomes the curator; the user reacts.

## Goal

Shift the product center of gravity from pull (I submit content, I search) to push (the system ingests, synthesizes, and tells me what's worth my attention). Build in three milestones; ship Milestone 1 first.

## Assumptions

- YouTube remains the sole input source (per user constraint — non-YouTube sources explicitly dropped).
- All push/event infrastructure is already in place (last commit: `telegram_notify`, event rendering, inline buttons, mute controls). No new delivery work required in Milestone 1.
- YouTube's public RSS feed (`https://www.youtube.com/feeds/videos.xml?channel_id={id}`) is the polling source — free, no API key, updates lag publish by ~hours which is acceptable for daily cadence.
- Scheduling model stays the same as the existing `yt-hidden-failed-cleanup` — Celery tasks invokable via `python -m` CLI, wired into cron (OpenClaw or launchd). No celery beat service.
- Solo user; no multi-tenant concerns.

## Milestones at a glance

| # | Milestone | Scope | Est. |
|---|---|---|---|
| 1 | **Watchlist + compression + throttling** | Ship first. Turns "I submit" into "system ingests overnight" with disk safeguards. | ~5 days |
| 2 | **Morning brief (advisor)** | LLM synthesis of overnight activity, persona-voiced. Revives Feature #3 with a daily cadence. | ~3 days |
| 3 | **Relevance scoring + knowledge graph** | Library self-curates as it scales. Powers smarter briefs. | ~6 days |

This plan details **Milestone 1** concretely; Milestones 2 and 3 are outlined for context.

---

## Milestone 1 — Watchlist + compression + throttling

### Goal

Subscribe to YouTube channels. Every night the system polls for new uploads, auto-ingests, notifies you with summaries. Stale content auto-compresses so disk stays healthy. Cost throttles keep the bill bounded.

### Data model

New migration `015_add_subscriptions_and_compression.py`:

```sql
CREATE TABLE channel_subscriptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  channel_id UUID NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  poll_frequency_hours INT NOT NULL DEFAULT 24,
  max_videos_per_poll INT NOT NULL DEFAULT 3,
  last_polled_at TIMESTAMPTZ,
  last_seen_video_ids TEXT[] NOT NULL DEFAULT '{}',
  videos_ingested_today INT NOT NULL DEFAULT 0,
  daily_counter_reset_at DATE,
  consecutive_failure_count INT NOT NULL DEFAULT 0,
  disabled_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (channel_id)
);

CREATE INDEX idx_subs_enabled_last_poll ON channel_subscriptions (enabled, last_polled_at);

-- Compression + activity tracking
ALTER TABLE videos ADD COLUMN last_activity_at TIMESTAMPTZ;
ALTER TABLE videos ADD COLUMN compressed_at TIMESTAMPTZ;
CREATE INDEX idx_videos_activity_compression ON videos (last_activity_at, compressed_at);
```

Post-migration data fill:
- `videos.last_activity_at := COALESCE(updated_at, created_at)` so nothing trips compression on day one.
- Auto-seed `channel_subscriptions` from existing channels that already have ≥1 completed video and `chat_enabled=true`. Default `enabled=true` — you can `/unsubscribe` anything you don't want.

### Pipeline — auto-ingest

```
Nightly 02:00 cron  ──►  python -m app.tasks.poll_subscriptions
                            │
                            ▼
        For each enabled subscription where (now - last_polled_at) >= poll_frequency_hours:
          1. Fetch RSS feed → list of recent videos
          2. Diff against last_seen_video_ids → new arrivals
          3. If videos_ingested_today >= max_videos_per_poll → skip rest
          4. If budget_remaining_today() <= 0 → skip all
          5. For each new video (capped):
                 submit via existing VideoSubmit logic
                 tag Job.attempt_creation_reason = 'auto_ingest'
          6. Update last_polled_at, last_seen_video_ids
          7. On exception: increment consecutive_failure_count;
             disable subscription after 3 consecutive failures
                   ↓
      Existing pipeline handles each new video
                   ↓
      embed task success → telegram_notify('video.completed', ...)
                   ↓
      Telegram ping identifies source: "📥 From @channel  Title  [Chat]"
```

### Pipeline — compression

```
Nightly 03:30 cron  ──►  python -m app.tasks.compress_stale_videos
                            │
                            ▼
        Find videos where:
          status = 'completed'
          AND compressed_at IS NULL
          AND last_activity_at < NOW() - interval 'N days'   (N = settings.compression_stale_days, default 30)
                            ▼
        For each:
          1. Resolve on-disk audio path (audio_dir + youtube_video_id + .wav)
          2. If the file exists → unlink it
          3. Set videos.compressed_at = NOW()
          4. Log "video_compressed" with bytes reclaimed
```

Window: **14 days** (`compression_stale_days = 14`).

Safety:
- Never compresses `status != 'completed'`.
- Transcript, summary, embeddings all live in Postgres — chat with a compressed video still works fully.
- Re-ingestion (user hits "Retry" or re-submits) will re-download via yt-dlp automatically; no special case needed.

### Pipeline — activity tracking

A small helper `touch_video_activity(db, video_id)` updates `last_activity_at = NOW()`. Called from:
- `POST /api/chat/sessions/{id}/messages` — when sources include this video
- `POST /api/agents/channel/{id}/sessions/{id}/messages` — always (whole channel scope)
- `POST /api/videos` — when user explicitly re-submits an existing video
- `/ask_video` in Telegram — when a video is matched

This keeps actively-used videos out of the compression sweep. Missing a few touch-sites is acceptable — worst case is an occasional re-download on re-chat after compression.

### Budget throttle

New setting `auto_ingest_daily_cost_cap_usd = 4.0`.

A helper `budget_remaining_today()` returns `min(daily_llm_budget_usd - today_cost, auto_ingest_daily_cost_cap_usd - today_auto_ingest_cost)`. The auto-ingest cost is tracked separately by tagging `LlmUsage` rows with `source='auto_ingest'` (new nullable column).

When the throttle engages, the poll task logs `auto_ingest_throttled` and emits `notify('cost.threshold_auto_ingest', {...})` — new event in `EVENT_RENDERERS`. Single notification per day via existing dedupe.

### Telegram commands (added to the manifest)

| Command | Args | Purpose |
|---|---|---|
| `/subscribe` | `<channel_url_or_handle>` | Add a subscription (creates channel record if not already ingested). |
| `/unsubscribe` | `<channel_name_or_keyword>` | Disable a subscription (keep its data; just stop polling). |
| `/subscriptions` | — | List subscriptions with state: enabled, next poll, daily count, last failure reason. |

`/subscribe` runs RSS fetch sync to verify the feed exists before persisting; errors back to the user immediately.

### Web endpoints (minimal)

- `GET /api/subscriptions` — list
- `POST /api/subscriptions` — create (body: `{channel_id_or_url}`)
- `PATCH /api/subscriptions/{id}` — toggle enabled, change frequency, adjust cap
- `DELETE /api/subscriptions/{id}` — remove

No new UI page in this milestone — Telegram is the canonical surface. A channel-detail "Subscribed ✓ / Subscribe" button can be added cheaply but isn't on the critical path.

### Implementation phases (Milestone 1 internal)

**Phase 1 — migration + model (0.5 day)**
- Alembic 015
- `app/models/channel_subscription.py` + `__init__.py` registration
- Auto-seed from existing channels
- Tests: migration applies cleanly, auto-seed respects `chat_enabled`

**Phase 2 — subscription service (1 day)**
- `app/services/subscriptions.py` — RSS fetch, diff detection, CRUD helpers
- `app/services/activity.py` — `touch_video_activity(db, video_id)`
- Tests: RSS parsing (including malformed feeds), diff correctness, touch hook

**Phase 3 — polling task + hooks (1 day)**
- `app/tasks/poll_subscriptions.py` (Celery task + CLI entry)
- Budget throttle with separated `source='auto_ingest'` cost tracking
- Circuit breaker on 3 consecutive failures
- `ATTEMPT_REASON_AUTO_INGEST` in pipeline_observability
- Touch-activity hooks added to the 4 sites listed above
- Tests: polling flow, throttle, circuit breaker

**Phase 4 — compression task (0.5 day)**
- `app/tasks/compress_stale_videos.py` (Celery task + CLI entry)
- Safety guards: only `status='completed'`, WAV-only
- Tests: chooses correct candidates, unlinks files, sets timestamps

**Phase 5 — Telegram + web endpoints (1 day)**
- `/subscribe`, `/unsubscribe`, `/subscriptions` in the command manifest
- `app/routers/subscriptions.py`
- Tests: command handlers, router endpoints

**Phase 6 — QA, docs, commit (0.5 day)**
- Live smoke: subscribe to one channel, force-run poll, watch a completion notification fire.
- Live smoke: create a dummy stale video, force-run compression, verify WAV gone + row marked.
- Update `docs/claude-diff-summary.md` and `docs/claude-test-results.txt`.
- Schedule the two cron entries (recommend OpenClaw cron; document in README).

Total: **~4.5 working days** for Milestone 1 end-to-end.

### Risks

- **RSS staleness (~hours).** Acceptable for daily cadence; worth noting.
- **YouTube rate limiting on yt-dlp.** Existing cookies config handles most cases; add `consecutive_failure_count` to back off per subscription.
- **Notification fatigue from many completions at once.** If 5 videos ingest overnight, you'd get 5 separate pings. Mitigation in Milestone 2 (morning brief batches them). For Milestone 1, add a per-day per-event soft cap that merges additional completions into a single "3 more ingested" summary.
- **Compression race with a chat in progress.** Safe: chat uses DB-resident artifacts only. Compression only removes the WAV on disk. Flagged anyway.
- **Runaway subscription.** A channel uploading 20 videos/day would blow past the per-sub cap (good). Global cost cap catches cross-subscription blow-ups (also good).
- **Auto-seeded subscriptions may surprise you.** First run will enable subs for every existing active channel. Mitigation: first run of `/subscriptions` sends a Telegram summary listing what was auto-seeded, with easy toggle.

### Done criteria (Milestone 1)

- Subscribe to a channel in Telegram (`/subscribe https://youtube.com/@lexfridman`). List via `/subscriptions`.
- Force-run the poll task. A new video from that channel gets ingested. A `video.completed` Telegram notification arrives identifying the subscription as the source.
- Compression task runs. A 30-day-stale video's WAV is removed; chat with it still works.
- Budget throttle engages when `auto_ingest_daily_cost_cap_usd` is hit; single Telegram notification fires; polling resumes the next day.
- 940+ tests passing.

---

## Milestone 2 — Morning brief (advisor revived)

Revives deferred Feature #3, repositioned as a **daily synthesis** rather than stats.

**Pipeline:** Cron 08:00 local → collect (videos ingested in last 24h, their summaries, any failures, any persona updates, yesterday's chat activity) → single Sonnet call → produces morning brief with:
- Top video of the day ("watch this one because…")
- 1-sentence synth of each other ingested video
- Any cross-video patterns (optional, richer once Milestone 3 knowledge graph ships)
- Any failures needing attention

Delivered via `telegram_notify` under new event `brief.morning`.

**Reuses persona system:** the brief's voice IS a persona. Default: an advisor-type persona (seeded in Milestone 1.5 as `scope_type='advisor', scope_id='morning_briefer'`). Long-term: pick any channel persona to voice it ("What would Lex say about today's crop?").

**Scope:** 1 new Celery task, 1 new event renderer, 1 new seed row. Minimal infra.

**Effort:** ~3 days. Tests hit mocked LLM responses.

---

## Milestone 3 — Relevance scoring + knowledge graph

### Relevance scoring (2 days)

- `videos.relevance_score` FLOAT, updated on touch events with time-decay nightly.
- Videos below threshold + compressed for 60+ days → `archived=true`, excluded from default search.
- `/unarchive <keyword>` in Telegram to bring back.

Keeps search quality high as the library scales to thousands of videos (which it will, with auto-ingest).

### Knowledge graph (4 days)

- `entities` and `claims` tables, populated by an LLM extraction step after `generate_embeddings`.
- Powers advanced queries: "when did speaker X change their mind about Y", "which recent videos contradict prior claims".
- Most importantly: feeds the morning brief's synthesis. Without the graph, briefs describe videos individually; with it, they describe patterns.

## Deferred (explicitly)

- **Non-YouTube sources** (user constraint).
- **Real-time / streaming mode** (anti-proactive).
- **Multi-modal OCR on slides** (revisit if brief quality is blocked by missing visual context).
- **Panel mode** (tier 2 persona work).
- **Public sharing / multi-user** (solo-user product).

## Verification (every milestone)

- New tests added per file; full suite stays green.
- End-to-end smoke: force-run the scheduled task, observe the Telegram side effect.
- Update `docs/claude-diff-summary.md` and `docs/claude-test-results.txt` per CLAUDE.md handoff.
- Commit to `main` with descriptive commit messages and push.

## Decisions (confirmed with user)

1. **Poll frequency:** `24h` — one nightly run.
2. **Auto-seed:** enable subscriptions for every active channel on migration. `/subscriptions` lists them so the user can mute individually.
3. **Compression window:** `14 days` untouched → WAV deleted.
4. **Daily auto-ingest cost cap:** `$4.00 USD`.
