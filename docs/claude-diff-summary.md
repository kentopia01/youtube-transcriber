# Claude Diff Summary — Telegram full parity + push notifications (2026-04-18)

## What shipped

Telegram bot now covers ~all daily-use features and proactively pings you
for meaningful events regardless of source (web, bot, cron, retry).

- **Phase A — commands:** `/submit`, `/queue`, `/search`, `/ask_video`, `/refresh_persona`, `/cost`, `/notify`, `/help`. Driven by a single `COMMANDS` manifest that also registers with Telegram's native `setMyCommands` so `/` shows autocomplete.
- **Phase B — notifier:** Source-agnostic push events (`video.completed`, `video.failed`, `persona.generated/refreshed`, `channel.queued`, `cost.threshold_80`, `cost.threshold_100`, `digest.weekly`). Hooked into `record_pipeline_failure`, `check_budget`, `generate_channel_persona_task`, `embed` task tail, and channel submission router. Fire-and-forget with in-process dedupe + mute state file.
- **Phase C — inline action buttons:** Every notification carries tap-to-act buttons (Chat / Retry / Open). A single `CallbackQueryHandler` dispatches `domain:action:arg`.
- **Phase D — weekly digest:** `tasks.weekly_telegram_digest` computes 7-day stats (videos ingested/completed/failed, jobs failed, personas built, LLM spend, top channels) and sends via the same notifier. Callable as a Celery task or CLI entry (`python -m app.tasks.weekly_digest`).

**Live verified:** weekly digest sent successfully to Telegram with real library stats; `/submit` exercised end-to-end against the web API.

## Files

### New

| File | Purpose |
|---|---|
| `app/services/telegram_notify.py` | Fire-and-forget notifier (HTTP API directly, no python-telegram-bot framework dep, sync-safe). Mute state reader, dedupe, token check. |
| `app/services/telegram_messages.py` | Renderer per event type. Returns `{text, reply_markup, parse_mode, dedupe_key}`. |
| `app/tasks/weekly_digest.py` | Weekly digest Celery task + CLI entry. Pure SQL aggregation. |
| `tests/test_telegram_phase_a.py` (12) | Manifest, `/help`, `/submit`, `/refresh_persona`, `/notify` — state file, mute specifics, unknown-event rejection. |
| `tests/test_telegram_notify.py` (14) | All 7 renderers, dispatch, mute, global-off, dedupe, unknown/missing-token/network-error safety, wiring from `record_pipeline_failure` and `check_budget`. |
| `tests/test_telegram_callbacks.py` (9) | Auth, invalid format, unknown action, dispatcher table, `_cb_job_retry` HTTP success + failure. |
| `tests/test_weekly_digest.py` (3) | Zero-activity path, populated digest, task-invokes-notifier. |

### Modified

- `app/config.py` — `telegram_notify_enabled`, `telegram_notify_muted_events`, `telegram_notify_state_path`, `internal_web_base_url`.
- `app/telegram_bot.py` — added 8 Phase-A commands + manifest + `/help` + `post_init` to `setMyCommands` + `CallbackQueryHandler` + dispatcher + 6 callback helpers. Fixed `LLMUsage` import alias.
- `app/services/pipeline_recovery.py` — emits `video.failed` at tail of `record_pipeline_failure`.
- `app/services/cost_tracker.py` — emits `cost.threshold_80` at 80% and `cost.threshold_100` at 100% before raising.
- `app/tasks/generate_persona.py` — captures pre-upsert persona existence to emit `persona.generated` vs `persona.refreshed` correctly.
- `app/tasks/embed.py` — emits `video.completed` at success tail (in addition to existing persona enqueue).
- `app/routers/channels.py` — emits `channel.queued` after successful submission.
- `app/tasks/celery_app.py` — registers `app.tasks.weekly_digest`.
- `tests/test_telegram_bot.py` — handler count assertion 12 → 21 (19 commands + 1 callback + 1 message).
- `tests/test_persona_task_and_trigger.py` — patches `app.services.persona.get_persona` in three tests to keep up with the pre-upsert check.

## Pipeline

```
Event source (any)                        Shared emit point
────────────────                          ─────────────────
Video embed succeeds   ─►  app/tasks/embed.py  ─►  notify("video.completed")
Job permanently fails  ─►  record_pipeline_failure  ─►  notify("video.failed")
Persona built          ─►  generate_channel_persona_task tail  ─►  notify("persona.generated|refreshed")
Channel submitted      ─►  /api/channels POST  ─►  notify("channel.queued")
LLM cost crosses 80/100%  ─►  check_budget  ─►  notify("cost.threshold_*")
Weekly cron tick       ─►  weekly_telegram_digest  ─►  notify("digest.weekly")

notify() → EVENT_RENDERERS[event](payload) → {text, reply_markup, dedupe_key}
       → _dedupe_allow (60s window) → _send → HTTPS POST sendMessage
```

## User surface

### Commands (19 total; 8 new)

| Category | Commands |
|---|---|
| Getting started | `/start`, `/help` |
| Content | `/submit`, `/queue`, `/search` |
| Chat | `/new`, `/sessions`, `/channels`, `/ask_channel`, `/ask_video`, `/refresh_persona` |
| Library | `/status`, `/videos`, `/ragstatus`, `/enable`, `/disable`, `/toggle` |
| Admin | `/cost`, `/notify` |

All appear in Telegram's native `/` autocomplete.

### Notification events

| Event | Default | Mute via |
|---|---|---|
| `video.completed` | on | `/notify off video.completed` |
| `video.failed` | on | `/notify off video.failed` |
| `persona.generated` | on | `/notify off persona.generated` |
| `persona.refreshed` | on | `/notify off persona.refreshed` |
| `channel.queued` | on | `/notify off channel.queued` |
| `cost.threshold_80` | on | `/notify off cost.threshold_80` |
| `cost.threshold_100` | on | `/notify off cost.threshold_100` |
| `digest.weekly` | on | `/notify off digest.weekly` |

`/notify off` mutes everything; `/notify status` inspects current state.

### Inline action buttons

- `video:chat:<id>` / `video:open:<id>`
- `channel:open:<id>`
- `job:retry:<id>` (POSTs `/api/jobs/{id}/retry`)
- `persona:chat:<cid>` / `persona:refresh:<cid>`

## Weekly digest

- `tasks.weekly_telegram_digest` — Sunday 18:00 recommended (wire via OpenClaw cron or launchd calling `python -m app.tasks.weekly_digest`).
- Pure stats; no LLM.
- Stats: videos ingested / completed / failed, jobs failed, personas built/refreshed, weekly LLM spend, top 5 channels by new videos.

## Decisions baked in

- **Notifications on by default**, mute per-event via `/notify off <event>`.
- **Cost alerts at 80% and 100%** of daily cap. Reuses existing `check_budget` logic.
- **Weekly digest, no daily**, explicitly per user request.
- **In-process 60s dedupe** on the `(event_type, dedupe_key)` pair.
- **Solo user = file-based prefs** (`/tmp/yt-chatbot/notify_state.json`). No new DB table.
- **Submit URL path: HTTP to the web API** from the bot — reuses all existing pipeline-attempt guards, no logic duplication.

## Risks

- **Weekly digest schedule not wired** — task exists and runs successfully; scheduling via OpenClaw cron or a launchd plist is a one-liner left to the operator (documented at the top of `weekly_digest.py`).
- **Web container restart cadence** — every ORM change requires `docker compose restart web`. Already familiar to the workflow.
- **Telegram network failures** swallowed — trade-off: notifications can be silently dropped. Acceptable for a personal tool; deliberate.
- **Dedupe is in-process** — if the bot, web, and workers independently send the same event (shouldn't but theoretically could), the user could get duplicates. Not observed in practice; acceptable.

## Deferred

- Feature #3 advisor brief (LLM-generated recommendations). The weekly digest is the stats-only placeholder; Feature #3 stacks on top when we return to it.
- Multi-user support. Out of scope; solo bot.
- Panel mode, speaker voiceprint clustering, cross-channel identity.

## Verification

- **pytest:** 933 passed, 0 failed (+38 new tests across 4 files). Full output + live smoke evidence in `docs/claude-test-results.txt`.
- **Live smoke:** weekly digest task invoked against the real DB; stats rendered and Telegram `sendMessage` returned HTTP 200 in bot logs. `/submit` exercised end-to-end on an already-processed URL; bot reply matched expected shape.
- **Bot startup:** `telegram_commands_registered count=19` confirms Phase A + `setMyCommands`.

## Plan deviations

None. Shipped exactly what `docs/claude-plan.md` described for Phases A–D.
