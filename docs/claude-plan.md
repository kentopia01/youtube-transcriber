# Claude Plan — Cleanup + digest + time-based persona refresh (2026-04-20)

Status: **proposed, awaiting go-ahead.** Four items, scope ranges from 10-min hygiene to a ~3-day feature ship. Items are independent; ship in any order.

## Goal

Close the four real gaps from yesterday's health report:

1. Clean up a lone video stuck in `transcribed` state + prevent recurrence.
2. Dismiss the 25 legacy failures cluttering ops views.
4. Ship Milestone 2's morning digest so notification fatigue never arrives.
7. (reframed) Switch persona-refresh from "+5 videos counter" to a daily time-based sweep that only fires when the channel has actually gotten new content.

Items #3, #5, #6, #8 from the report are deferred and not planned here.

## Assumptions

- All four ship as independent Celery tasks + CLI entrypoints wired to OpenClaw cron (same pattern as `yt-poll-subscriptions`, `yt-compress-stale`, `yt-hidden-failed-cleanup`).
- Morning digest reuses `telegram_notify` + `EVENT_RENDERERS` infra; no new delivery wiring.
- `videos.dismissed_at` is the right abstraction for item #2 (durable; queryable; reversible).
- Time-based persona refresh supersedes — not augments — the existing `+5 videos` counter.

---

## Item 1 — Stuck `transcribed` video (small, ~30 min)

### Problem

One video in the library has `status='transcribed'` (should have progressed through `summarized → completed`). Happened because a stage got reaped mid-pipeline. The reaper flagged the Job but never reconciled `Video.status`.

### Design

Two parts:

**(a) Immediate cleanup.** One-shot SQL to mark the stuck row as failed so it re-enters normal retry flow:

```sql
UPDATE videos
SET status = 'failed',
    error_message = 'Reconciled: stuck in transcribed state with no active job'
WHERE status = 'transcribed'
  AND NOT EXISTS (
    SELECT 1 FROM jobs j
    WHERE j.video_id = videos.id
      AND j.status IN ('pending', 'queued', 'running')
  );
```

**(b) Prevent recurrence.** New task `reconcile_stale_video_status` runs every 30 min (piggyback on the existing stale-job-reaper cron). Walks all videos in any non-terminal non-completed state (`pending`, `downloaded`, `transcribed`, `diarized`, `summarized`) and cross-checks them against `jobs`. If the video has no active job AND no recent job update (≥ `pipeline_stale_timeout_queued_minutes` + buffer), mark it `failed` so it's visible to retry flows.

### Files

- **New** `app/tasks/reconcile_video_status.py` — Celery task + CLI entry + tests
- **New** `tests/test_reconcile_video_status.py`
- **Modify** `openclaw cron` — add a new 30-min schedule or extend the existing reaper

### Effort & risk

~30 min. Risk: minimal — the reconciler only looks at videos with no active job and updates them conservatively.

---

## Item 2 — Dismiss legacy failures (small, ~1 hour)

### Problem

25 failures from the April-18 backfill clutter `GET /api/jobs`, the `/queue` Telegram command, and the web `/queue` page. They won't be retried (the associated channels were unsubscribed from the watchlist) but they keep appearing in ops views.

### Design

Add `dismissed_at TIMESTAMPTZ` to `videos` + filter all queue/failed-listing views by `dismissed_at IS NULL`.

### Data model (alembic migration 016)

```sql
ALTER TABLE videos ADD COLUMN dismissed_at TIMESTAMPTZ;
ALTER TABLE videos ADD COLUMN dismissed_reason TEXT;
CREATE INDEX idx_videos_dismissed ON videos (dismissed_at) WHERE dismissed_at IS NULL;
```

Index is partial — only non-dismissed rows — keeps the existing queue queries cheap.

### API / UX

- `POST /api/videos/{id}/dismiss` — body `{reason?: string}` — idempotent
- `POST /api/videos/{id}/undismiss` — clears
- Telegram `/dismiss <keyword>` — mass-dismiss failed videos whose title matches
- `/queue` command filters `dismissed_at IS NULL`
- Web `/queue` page filters `dismissed_at IS NULL`
- Existing `POST /api/jobs/{id}/retry` un-dismisses if we retry a dismissed video (user intent = "actually I do care now")

### Migration-time cleanup

Post-migration SQL to dismiss the 25 existing legacy failures:

```sql
UPDATE videos v
SET dismissed_at = NOW(),
    dismissed_reason = 'legacy-backfill-failure: reaped during April 18 backfill'
WHERE v.status = 'failed'
  AND v.channel_id NOT IN (
    SELECT channel_id FROM channel_subscriptions WHERE enabled = true
  )
  AND v.created_at < '2026-04-19';
```

### Files

- **New** `alembic/versions/016_add_video_dismissed_at.py`
- **Modify** `app/models/video.py` — new column
- **Modify** `app/routers/videos.py` — new dismiss/undismiss endpoints
- **Modify** `app/routers/jobs.py`, `app/routers/pages.py` — filter out dismissed in queue listings
- **Modify** `app/telegram_bot.py` — `/dismiss <keyword>` command; filter `/queue`
- **New** `tests/test_dismiss.py`

### Effort & risk

~1 hour. Risk: low — pure data-model + filter. Reversible via `undismiss`.

---

## Item 4 — Morning digest (biggest; ~3 days)

### Problem

At N=3 channels today, you'd get 1-9 `video.completed` Telegram pings per night. As the watchlist grows, individual pings become noise. Need a single synthesized morning brief.

### Design

Scheduled Celery task `morning_digest` runs daily at 08:00 local. Collects the last 24h of activity across the library, asks Sonnet to synthesize, delivers via the existing `telegram_notify` pipe.

### Data

Inputs the task gathers (24h window):
- Videos completed (title + channel + duration + transcription summary excerpt)
- Jobs failed (and reason)
- Personas generated or refreshed
- LLM cost spent
- Chat sessions that happened (if any)

### Pipeline

```
Cron 08:00 local
  → gather_digest_inputs(db) → dict
  → render_digest_via_llm(inputs) → Markdown brief (single Sonnet call)
  → telegram_notify("digest.morning", {text: brief_md})
  → deliver via Telegram with inline [Chat with top pick] button
```

### LLM prompt (Sonnet-4-5; ~5k input / ~800 output; ≈$0.03 per run)

```
You are my morning research assistant. Summarize what happened overnight
in my YouTube library into a tight morning brief.

Inputs:
- Videos ingested in the last 24h (title, channel, duration, first 500 chars of summary)
- Any pipeline failures
- Any persona refreshes
- Yesterday's LLM spend

Format:
1. One-sentence opener (set the tone — "Quiet night", "Heavy news day on AI", etc.)
2. *Worth your time today:* one recommendation, 2-3 sentences on why
3. *Also ingested:* 2-5 one-line summaries of the rest
4. *Needs attention:* any failures (or "None")
5. Related: one follow-up question the user might ask

Never invent. If a video has no summary yet, say "still processing".
```

### Mute interaction

When morning digest is enabled (default on), we continue to fire `video.completed` individual pings but deduplicate at the digest level. Users who want **only** the digest can `/notify off video.completed`. Users who want only individuals can `/notify off digest.morning`. Sensible defaults: both on; digest arrives at 08:00; individual pings silent by default after the first 2 per day (new soft cap).

Actually simpler: make the digest opt-in for the first release.

### Persona voice (optional v1.1)

The digest's Sonnet call can take a persona prompt from `personas` where `scope_type='advisor'`. Seed one "morning_briefer" persona at migration time. If the user later picks a channel persona to voice it (via `/notify digest_voice <channel>`), replace the advisor prompt with the channel's persona prompt.

### Files

- **New** `app/tasks/morning_digest.py` — Celery task + CLI entry
- **New** `app/services/digest.py` — input gathering + LLM rendering
- **New** `tests/test_morning_digest.py`
- **Modify** `app/services/telegram_messages.py` — `digest.morning` renderer
- **Modify** `app/telegram_bot.py` — extend `/notify` to toggle `digest.morning`
- **Migration 017** — seed an advisor persona row for the briefer voice

### Effort & risk

~3 days. Risk: moderate — LLM output quality depends on prompt and a day's inputs, won't be perfect on day one. Mitigation: the infrastructure is independent of the formatter; bad output just means we iterate the prompt.

---

## Item 7 — Time-based persona refresh (small-medium, ~half-day)

### Problem

Currently persona refresh depends on `persona.videos_at_generation` + a `refresh_after_videos` counter. Embed-task hook enqueues refresh when `channel_needs_persona` returns true. Two failure modes observed:

- Counter drift if auto-ingest stalls (the increment happens at embed-completion, not at subscription-add)
- No sweep means a stale persona can linger indefinitely if the auto-trigger ever misses

### Design (per user's suggestion)

Daily cron `refresh_stale_personas` runs at 04:00 SG (after compression, before user wakes):

```
For each persona where scope_type = 'channel':
  channel_id = persona.scope_id
  new_completed_since = COUNT videos WHERE
      video.channel_id = channel_id
      AND video.status = 'completed'
      AND video.created_at > persona.generated_at
  if new_completed_since > 0:
      enqueue_channel_persona(channel_id, forced=True)
```

One query per persona. Tiny. Cheap.

### Sub-decisions

- **Remove `refresh_after_videos` from the persona row**? It's now redundant. Keep the column for one release cycle (no migration cost), stop reading it.
- **Keep the embed-hook auto-trigger for FIRST persona generation**? Yes — the time-based sweep doesn't handle the "channel crosses 3-video threshold" bootstrapping case. Embed-hook stays, but now only fires `channel_needs_persona` logic for channels with **no existing persona**. Refresh concern is entirely delegated to the daily sweep.
- **Notify on refresh?** Yes, `persona.refreshed` event is already wired. User sees `♻️ Persona refreshed` pings when the daily sweep fires one.

### Files

- **New** `app/tasks/refresh_stale_personas.py` — Celery task + CLI entry
- **Modify** `app/services/persona.py` — narrow `channel_needs_persona` to only the first-generation case (remove the `videos_since` math)
- **Modify** `app/tasks/embed.py` — adjust the comment reflecting narrower role of the embed hook
- **New** `tests/test_refresh_stale_personas.py`
- **OpenClaw cron** — add `yt-refresh-personas` at 04:00 SG daily

### Effort & risk

~4 hours. Risk: low. A refresh that runs "too often" costs ~$0.12 per run — we'd need a pathological case to budget-bust.

---

## Cost impact

Additive annual cost of all four items:

| Item | Per-day | Per-month | Notes |
|---|---:|---:|---|
| #1 reconcile_video_status | $0 | $0 | no LLM |
| #2 dismiss | $0 | $0 | no LLM |
| #4 morning digest | $0.03 | ~$1 | one Sonnet call/day |
| #7 refresh sweep | $0–1.20 | $0–36 | scales with channel churn; typical ~$0.10 |

Trivial against the $4 auto-ingest cap.

---

## Ship order recommendation

1. **#1** (today, 30 min) — removes the anomaly; free safety
2. **#2** (today, 1 hour) — removes 25 distraction rows from ops views
3. **#7** (this week, 4 hours) — fixes the persona-refresh drift risk
4. **#4** (next ship, 3 days) — addresses notification fatigue before the watchlist grows

#1, #2, #7 can bundle into one commit+push. #4 gets its own milestone.

## Verification

- Each item ships with unit tests
- `/queue` filters empirically verified after #2 commit
- Morning digest first run verified via manual `python -m app.tasks.morning_digest`
- Refresh sweep first run verified via manual CLI on a channel known to have new completions

## Deferred

- #3 credit-balance alert (account-level API credit monitoring)
- #5 RSS monitoring / simplification
- #6 `/ask_channel` rate limit
- #8 library chat upgrade to Sonnet
- Remainder of Milestone 3 (relevance scoring + knowledge graph)
