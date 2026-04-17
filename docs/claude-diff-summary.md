# Claude Diff Summary — Milestone 1: watchlist + compression + budget throttle (2026-04-18)

## What shipped

The system now curates content autonomously. Every night it polls the channels
you've subscribed to, auto-ingests new uploads through the existing pipeline
(with push notifications on completion), and compresses WAV files for videos
you haven't touched in 14+ days.

**Live-verified on first run:**
- **Poll:** 17 auto-seeded subscriptions, 46 videos ingested (respecting 3-per-channel cap), one circuit-breaker-worthy failure (live event) handled cleanly.
- **Compression:** 20 stale videos reclaimed **1.4 GB** of disk. All remain chat-able.
- **Tagging:** all 47 new jobs are marked `attempt_creation_reason='auto_ingest'` — LLM spend will flow to the separate autonomous-work budget.

## Files

### New

| File | Purpose |
|---|---|
| `alembic/versions/015_add_subscriptions_and_compression.py` | `channel_subscriptions` table, `videos.last_activity_at`/`compressed_at` cols, `llm_usage.source` tag, auto-seed. |
| `app/models/channel_subscription.py` | ORM model. |
| `app/services/subscriptions.py` | RSS fetch + parse, diff detection, CRUD, poll-state helpers (is-due / reset-counter / mark-success / mark-failure), resolve-channel-by-query, `touch_video_activity`. |
| `app/tasks/poll_subscriptions.py` | Celery task + CLI. Iterates subscriptions, submits new videos via the web API, tags jobs, honors per-sub + global caps, circuit-breaker after 3 consecutive failures. |
| `app/tasks/compress_stale_videos.py` | Celery task + CLI. Deletes on-disk WAVs for completed videos stale ≥ `compression_stale_days` (14); marks `compressed_at`; keeps all DB-resident artifacts. |
| `app/routers/subscriptions.py` | `GET/POST /api/subscriptions`, `PATCH/DELETE /api/subscriptions/{id}`. |
| `tests/test_subscriptions_model.py` (3) | Model construction + Video compression fields. |
| `tests/test_subscriptions_service.py` (18) | RSS parse (incl. malformed), diff correctness, poll-state helpers, resolver ranking. |
| `tests/test_poll_subscriptions.py` (7) | End-to-end task flow: no-new / up-to-cap / budget-exhausted / RSS failure / circuit-breaker; cost-tracker helpers. |
| `tests/test_compress_stale_videos.py` (6) | Path resolution, unlink + timestamp set, missing-wav safety, disabled gate, integration. |
| `tests/test_subscriptions_api.py` (12) | Router endpoints + Telegram `/subscribe` `/unsubscribe` `/subscriptions`. |

### Modified

- `app/config.py` — `auto_ingest_daily_cost_cap_usd=4.0`, `auto_ingest_poll_hours_default=24`, `auto_ingest_max_videos_per_poll_default=3`, `compression_stale_days=14`, `compression_enabled=True`.
- `app/models/__init__.py` — exports `ChannelSubscription`.
- `app/models/video.py` — `last_activity_at`, `compressed_at` mapped columns.
- `app/models/llm_usage.py` — `source` column.
- `app/services/cost_tracker.py` — `set_cost_source`, `source_for_attempt_reason`, `get_today_cost_by_source`, `auto_ingest_budget_remaining`; contextvar read in `record_usage`.
- `app/services/pipeline_observability.py` — `ATTEMPT_REASON_AUTO_INGEST`.
- `app/tasks/cleanup.py`, `app/tasks/summarize.py` — set cost-source contextvar at task entry based on job reason.
- `app/tasks/celery_app.py` — registers `poll_subscriptions` + `compress_stale_videos`.
- `app/routers/chat.py`, `app/routers/agents.py`, `app/telegram_bot.py` — touch `last_activity_at` on cited videos (chat/agents) and matched videos (`/ask_video`).
- `app/main.py` — includes the `subscriptions` router.
- `app/telegram_bot.py` — three new commands (`/subscribe`, `/unsubscribe`, `/subscriptions`) wired through the existing manifest.
- `tests/test_telegram_bot.py`, `tests/test_telegram_phase_a.py` — handler/manifest counts bumped (21→24 handlers, 19→22 commands).

## Pipeline

```
Nightly 02:00 cron  ──►  python -m app.tasks.poll_subscriptions
                            │
    ┌───────────────────────┴─────────────────┐
    │ for each due, enabled subscription:     │
    │   1. fetch YouTube RSS                  │
    │   2. diff vs last_seen_video_ids        │
    │   3. check auto_ingest_budget_remaining │
    │   4. submit up to max_videos_per_poll   │
    │   5. tag each job attempt_creation_reason = 'auto_ingest'
    │   6. update last_polled_at, last_seen   │
    │   7. on failure: ++counter, disable at 3│
    └───────────────────────┬─────────────────┘
                            │
                            ▼
                 Existing pipeline ingests
                            │
                            ▼
         embed success → telegram_notify('video.completed')
                         ↓
                  Push arrives in Telegram with [Chat] button
```

```
Nightly 03:30 cron  ──►  python -m app.tasks.compress_stale_videos
                            │
    Find completed videos where last_activity_at < NOW() - 14 days
    and compressed_at IS NULL.
                            │
    For each: unlink the WAV, mark compressed_at.
    Transcript + summary + embeddings remain in Postgres.
                            ▼
                 Disk reclaimed; chat still works.
```

```
Activity touch (prevents compression of active content):
  chat message with citations ─►  touch_video_activity(vid) for each source
  agent message with citations ─► touch_video_activity(vid) for each source
  /ask_video match  ────────────► touch_video_activity(match.id)
```

## Cost accounting

Autonomous work is now segregated from manual work. All LLM calls made while
processing an `auto_ingest`-tagged job inherit `source='auto_ingest'` via a
`ContextVar` set at task entry. The `/cost` Telegram command shows total spend;
a new `auto_ingest_budget_remaining()` helper gates the poll task so the autonomous-
work side can never exceed `$4/day` (configurable via `auto_ingest_daily_cost_cap_usd`).

## User surface

**3 new Telegram commands** (now 22 total, all in `/` autocomplete via `setMyCommands`):
- `/subscribe <channel URL>` — add a subscription.
- `/unsubscribe <name>` — disable by keyword.
- `/subscriptions` — list with per-sub state (enabled, last polled, today's count, disabled reason).

**4 new REST endpoints** under `/api/subscriptions` for future web-UI support.

## Decisions locked

1. **Poll frequency:** `24h` default.
2. **Auto-seed:** enable subscriptions for every existing active channel on migration (17 seeded on first apply).
3. **Compression window:** `14 days` untouched → WAV deleted.
4. **Daily auto-ingest cost cap:** `$4.00`.

## Scheduling (operator step)

Two cron entries to wire before bed:

```bash
# Poll subscriptions at 02:00 nightly
openclaw cron add yt-poll-subscriptions \
  --schedule "0 2 * * *" \
  --command "cd /Users/sentryclaw/Projects/youtube-transcriber && \
             source .env.native && .venv-native/bin/python -m app.tasks.poll_subscriptions"

# Compression sweep at 03:30 nightly
openclaw cron add yt-compress-stale \
  --schedule "30 3 * * *" \
  --command "cd /Users/sentryclaw/Projects/youtube-transcriber && \
             source .env.native && .venv-native/bin/python -m app.tasks.compress_stale_videos"
```

Until these are scheduled, both tasks are available as manual-run CLI entries.

## Risks

- **RSS staleness (~hours).** Acceptable for daily cadence.
- **46 videos queued on first smoke.** Real LLM spend is in-flight; the `$4` auto-ingest cap bounds it. This is the system working as designed.
- **Notification fatigue** on days with many completions. Milestone 2 (morning brief) will batch these into one daily message.
- **Compression race** — safe by construction (chat uses DB-resident artifacts only).
- **YouTube RSS occasionally returns scheduled live events** as future videos; yt-dlp returns a clear 400 and the per-video submit fails gracefully (seen in the live smoke).

## Verification

- **pytest: 978 passed, 1 skipped.** Full verbose output in `docs/claude-test-results.txt`.
- **Live poll:** 17 subs processed, 46 ingests, tagging confirmed at DB level (`attempt_creation_reason='auto_ingest'` × 47).
- **Live compression:** 20 stale videos compressed, 1.4 GB reclaimed.
- **Bot:** 22 commands registered with Telegram, both new tasks visible to post worker.

## Plan deviations

None. Shipped exactly what `docs/claude-plan.md` described for Milestone 1.

## What's next (Milestone 2 & 3 outlines — unchanged)

- **Milestone 2:** Morning brief. Batches overnight completions into a single LLM-synthesized "here's what was ingested, here's the one worth your time" message at 08:00. Reuses the advisor persona pattern. ~3 days.
- **Milestone 3:** Relevance scoring + knowledge graph. Auto-archives low-engagement videos; extracts entities and claims to power smart cross-video briefs. ~6 days.
