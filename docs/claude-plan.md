# Claude Plan — Telegram Full Parity + Event Notifications (2026-04-18)

Status: **proposed, awaiting go-ahead.**

## Goal

Make the Telegram bot the primary control surface for the transcriber. Two things:

1. **Feature parity via commands** — `/submit`, `/queue`, `/search`, `/ask_video`, `/refresh_persona`, `/cost`, `/notify`, `/help`.
2. **Source-agnostic push notifications** — the bot pings when meaningful things happen regardless of whether the triggering action came from the bot, web, cron, or a retry.

No multi-user work. Single owner (`TELEGRAM_ALLOWED_USERS=[5815973193]`) is the only consumer.

## Assumptions

- Reuse existing services: `encode_query`, `semantic_search`, `chat_with_context`, `get_persona`, `enqueue_channel_persona`, `submit_video`-style routers.
- Worker processes already have Redis/DB access; they can issue a simple HTTPS POST to the Bot API without loading the full `python-telegram-bot` framework. Use `requests` with a 2s timeout.
- Decision defaults (flag if you want to override):
  - **Notifications on by default.** Toggle via `/notify off <event>` or `/notify off` (mute all).
  - **Cost alerts:** 80% + 100% of daily budget (existing `check_budget`).
  - **Weekly digest:** Sundays 18:00 local, stats-only (not the LLM-generated brief — that's Feature #3).

## Architecture

### Where notifications come from

Regardless of how a job was started, notifications fire from the **shared state-transition code**, not from entry points.

```
Web /api/videos ─┐
Bot /submit     ─┼─► Pipeline tasks ─► Celery signals ───► telegram_notify.notify()
Cron retry      ─┤      + failure recorder ────────────┤
Auto-trigger    ─┘                                       │
                                                         │
Budget service ──► check_budget() threshold ─────────────┤
Persona task   ──► tail hook ────────────────────────────┘
```

### Emitter design (minimal, no bus)

- **Celery signals** — `task_success` (filtered to `tasks.generate_embeddings`, `tasks.generate_channel_persona`) and `task_failure` (none directly — we wrap through `record_pipeline_failure` instead for richer context).
- **Explicit emits** at four sites only:
  - `record_pipeline_failure` tail — permanent job failure
  - `generate_channel_persona_task` tail — persona built / refreshed
  - `check_budget` threshold crossing — cost alert
  - Channel submission router — channel discovery queued

This avoids a bus abstraction while keeping coverage complete.

### Notifier module

`app/services/telegram_notify.py`:
```python
def notify(event_type: str, payload: dict) -> None:
    """Fire-and-forget. Reads TELEGRAM_BOT_TOKEN + chat_id from env. No-ops if
    notifications are disabled or the event is muted. Catches all exceptions."""
```

Templates live in `app/services/telegram_messages.py` — one function per event type producing `(text, reply_markup)`.

### Inline action buttons

Each notification includes one or two buttons via Telegram's `InlineKeyboardButton` + `callback_data`. Callbacks route on a prefix:

```
video:chat:<video_id>         → open a new chat session for that video
video:open:<video_id>         → send the video's summary
job:retry:<job_id>            → enqueue retry
persona:refresh:<channel_id>  → trigger generate-persona
persona:chat:<channel_id>     → open persona chat session
```

A single `CallbackQueryHandler` with a prefix-based dispatcher. Small and extensible.

## Commands

### New / changed

| Command | Args | Purpose |
|---|---|---|
| `/help` | — | Auto-generated list of all commands, grouped, with args and one-line descriptions. |
| `/submit` | `<url>` | Auto-detect video vs channel URL, enqueue via the existing submit services. |
| `/queue` | — | Running and most recent failed jobs with inline `[Retry]` on failures. |
| `/search` | `<query>` | Top 5 chunks with `[Chat about this]` inline buttons. |
| `/ask_video` | `<keyword> <q>` | Symmetric to `/ask_channel`; filter retrieval to one video. |
| `/refresh_persona` | `<channel>` | Kicks existing endpoint. |
| `/cost` | — | Today / month spend vs daily budget. |
| `/notify` | `on`, `off`, `off <event>`, `on <event>`, `status` | Toggle notifications. |

### Unchanged

`/start`, `/new`, `/sessions`, `/status`, `/videos`, `/ragstatus`, `/enable`, `/disable`, `/toggle`, `/channels`, `/ask_channel`.

### Command registration

Single `COMMANDS` manifest in `app/telegram_bot.py` drives:
- `CommandHandler` registration for the bot
- `bot.set_my_commands(...)` at startup so `/` shows a native autocomplete menu
- `/help` output (grouped by category)

One source of truth. Add a command → it appears everywhere.

## Notification event catalog

| Event type | Fired when | Message | Buttons |
|---|---|---|---|
| `video.completed` | `generate_embeddings` task success | "✅ Title (1h 20m, 4 speakers)" | `[Chat] [Open]` |
| `video.failed` | `record_pipeline_failure` on permanent failure | "❌ Title failed at `stage`: reason" | `[Retry] [Details]` |
| `persona.generated` | `generate_channel_persona_task` success, first time | "✨ New persona: Name (conf 0.87)" | `[Chat]` |
| `persona.refreshed` | same, on refresh | "♻️ Name persona refreshed" | `[Chat]` |
| `channel.queued` | Channel submission | "📥 Queued N videos from @handle" | `[Queue]` |
| `cost.threshold_80` | `check_budget` crosses 80% | "⚠️ $X.XX of $Y.YY daily cap (80%)" | — |
| `cost.threshold_100` | `check_budget` crosses 100% | "🛑 Daily LLM budget exceeded ($Y.YY)" | — |
| `digest.weekly` | Sundays 18:00 | Multi-line stats | — |

Each mutable at individual granularity via `/notify off <event_type>`.

## State for notification preferences

Single `telegram_notify_state` JSON file at `/tmp/yt-chatbot/notify_state.json` (or same dir as bot lock). Contents: `{"enabled": true, "muted_events": []}`. Read on each notify call; written by `/notify`. No new DB table — overkill for one user.

## Implementation phases

**Phase A — commands + /help (1.5 days)**
- `COMMANDS` manifest
- Implement missing handlers (`/submit`, `/queue`, `/search`, `/ask_video`, `/refresh_persona`, `/cost`, `/notify`, `/help`)
- `set_my_commands` at startup
- Tests: handler + response for each new command

**Phase B — event hub + source-agnostic notifications (1.5 days)**
- `app/services/telegram_notify.py` (send-only client, fire-and-forget)
- `app/services/telegram_messages.py` (templates)
- Celery signal subscribers (filtered by task name)
- Explicit emits in `record_pipeline_failure`, `generate_channel_persona_task`, `check_budget`, channel submission router
- State file for mute preferences
- Tests: signal handler dispatch, template correctness, mute honored

**Phase C — inline action callbacks (1 day)**
- `CallbackQueryHandler` with prefix router
- Handlers: `video:chat`, `video:open`, `job:retry`, `persona:refresh`, `persona:chat`
- Tests: dispatch table + side-effect assertions

**Phase D — weekly digest (0.5 day)**
- Celery beat entry `weekly_telegram_digest`, Sundays 18:00
- Pulls 7-day DB stats (videos ingested, failures, personas built, cost)
- Renders to Markdown, sends via `telegram_notify.notify('digest.weekly', ...)`
- No LLM — simple aggregation. Feature #3 stacks on this later.

Total: ~4.5 working days.

## Files touched

### New
- `app/services/telegram_notify.py`
- `app/services/telegram_messages.py`
- `app/tasks/weekly_digest.py`
- `tests/test_telegram_commands.py`
- `tests/test_telegram_notify.py`
- `tests/test_telegram_callbacks.py`
- `tests/test_weekly_digest.py`

### Modified
- `app/telegram_bot.py` — `COMMANDS` manifest, new handlers, callback handler, `/help`, `set_my_commands`
- `app/services/pipeline_recovery.py` or `record_pipeline_failure` site — emit `video.failed`
- `app/tasks/generate_persona.py` — emit `persona.generated|refreshed` at tail
- `app/tasks/embed.py` — add Celery signal subscription for `video.completed`
- `app/services/cost_tracker.py` — emit `cost.threshold_80|100`
- `app/routers/channels.py` — emit `channel.queued` on submission
- `app/config.py` — `telegram_notify_enabled`, `telegram_notify_muted_events`
- `app/tasks/celery_app.py` — include `weekly_digest` + beat schedule

## Risks

- **Telegram API timeouts blocking workers.** 2s request timeout + broad try/except in notify. Budget: worst case ~10s added latency on a pathological network partition, spread across multiple events. Acceptable for a solo-user tool.
- **Notification spam on retry storms.** Deduplication window (same event type + same key in 60s) in the notifier. Simple in-memory dict on the bot process.
- **Callback data size limit** (Telegram allows 64 bytes). UUIDs fit. If we ever need more, stash a callback_id → payload in Redis with TTL.
- **Testing Telegram-specific UI without a live bot.** All notifier unit tests mock `requests.post`; integration test sends to a test chat if `TELEGRAM_TEST_CHAT_ID` is set.

## Explicitly deferred

- **Feature #3 (weekly advisor brief).** The weekly digest in Phase D is stats-only, not LLM-generated recommendations. When we return to Feature #3, it becomes a second digest persona.
- **Multi-user** — not in scope; app is solo.
- **Rich web auth** for `/submit` URLs — we trust the allowlisted user.

## Verification

- Every phase adds pytest coverage; full suite stays green.
- End of Phase B: manually trigger a video.failed and verify the message + retry button reach Telegram.
- End of Phase C: tap each callback button path and confirm downstream effect.
- End of Phase D: set the beat interval to 1 min, let it fire, verify digest content.
- Update `docs/claude-diff-summary.md` and `docs/claude-test-results.txt` per CLAUDE.md handoff.
