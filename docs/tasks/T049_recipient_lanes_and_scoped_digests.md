# T049 - Recipient Lanes and Scoped Digests

## Status
Planned, gated.

Implementation must not start until the current YouTube catch-up pipeline has fully drained and Ken explicitly reopens this task for build.

## Objective
Add lightweight recipient lanes so multiple Telegram users can configure their own YouTube channel digest lists while sharing the existing transcript processing library.

Ken's personal digest must stay lane-scoped to Ken's configured channels, while Ken keeps admin/operator visibility across every lane for monitoring and troubleshooting.

## Why it matters
The current bot is a broad single-operator surface. It has one global subscription table and exposes chat, search, queue, RAG, notification, and admin commands to allowed Telegram users. Adding another user through the current allowlist would be too permissive and could let them mutate Ken's subscriptions or use features outside the intended digest workflow.

Recipient lanes give the right middle ground:
- shared compute and shared transcript/report storage
- per-recipient channel configuration and digest delivery
- restricted Telegram command surface for non-admin users
- admin visibility for Ken without polluting Ken's personal digest

## Current Baseline
- `channels`, `videos`, `jobs`, `summaries`, `transcriptions`, `embedding_chunks`, `video_reports`, personas, and chat data are global.
- `channel_subscriptions` is global and unique by `channel_id`.
- Telegram access is currently gated by `telegram_allowed_users`, not by per-command or per-lane authorization.
- The Telegram command manifest currently includes owner/operator commands such as `/submit`, `/queue`, `/search`, chat/persona commands, RAG toggles, `/dismiss`, `/cost`, and `/notify`.

## Product Contract
### Restricted lane users
Allowed commands:
- `/start` - short welcome
- `/help` - show only restricted lane commands
- `/subscribe <channel>` - add or enable a channel for the caller's lane
- `/unsubscribe <channel>` - disable a channel for the caller's lane
- `/subscriptions` - list the caller's lane subscriptions
- `/digest` - optional manual "send my lane digest now" command

Not allowed:
- search, chat, ask-video, ask-channel, video browsing, queue, retry, RAG toggles, persona refresh, notification controls, global cost, report/admin controls.

If a restricted user manually types a hidden command, return a short "not available for your lane" response.

### Ken personal lane
Ken has a normal recipient lane. Ken's personal digest must include only Ken-lane items.

### Ken admin capability
Ken's Telegram user should also have admin/operator capability across all lanes.

Admin commands:
- `/admin_help` - list admin-only commands
- `/lanes` - list all lanes and owners
- `/lane_status <lane>` - subscriptions, active jobs, recent completions/failures for one lane
- `/lane_failures <lane>` - failed/stuck items for one lane
- `/lane_digest <lane>` - preview or send a lane digest manually
- `/lane_retry <lane> <video/job>` - retry a lane-linked failed item
- `/queue` - global processing queue
- `/cost` - global LLM spend

Existing power-user commands may remain admin-only:
- `/search`, `/ask_video`, `/ask_channel`, `/videos`, `/channels`
- `/ragstatus`, `/enable`, `/disable`, `/toggle`
- `/dismiss`, `/refresh_persona`, `/notify`

## Proposed Data Model
### `digest_lanes`
Fields:
- `id`
- `label`
- `telegram_user_id`
- `telegram_chat_id`
- `timezone`
- `digest_enabled`
- `role` or capability flags, e.g. `restricted`, `admin`
- `created_at`, `updated_at`

Constraints:
- unique `telegram_user_id`
- unique lane label or slug

### `lane_subscriptions`
Fields:
- `id`
- `lane_id`
- `channel_id`
- `enabled`
- `poll_frequency_hours`
- `max_videos_per_poll`
- `last_polled_at`
- `last_seen_video_ids`
- `videos_ingested_today`
- `daily_counter_reset_at`
- `consecutive_failure_count`
- `disabled_reason`
- `created_at`, `updated_at`

Constraints:
- unique `(lane_id, channel_id)`

Reason:
Do not reuse the current global `channel_subscriptions` table for restricted users because unsubscribing from that table could mutate Ken's subscriptions.

### `lane_video_items`
Fields:
- `id`
- `lane_id`
- `video_id`
- `lane_subscription_id`
- `source` such as `lane_poll`, `manual_lane_add`, `backfill`
- `first_seen_at`
- `processing_job_id`
- `digest_delivered_at`
- `dismissed_at`, optional
- `created_at`, `updated_at`

Reason:
The same global video may belong to multiple lanes. A lane item records per-recipient ownership/digest state without duplicating processing.

## Service Design
### Lane resolution
Add a small service to resolve the caller:
- by `telegram_user_id`
- return lane and capabilities
- distinguish "recipient scope" from "admin scope"

### Role-aware Telegram manifest
Refactor command registration/help into role-aware manifests:
- restricted users see only lane commands
- Ken/admin sees lane commands plus `/admin_help`
- admin-only commands are rejected for restricted users even if manually typed

Telegram's native command menu may need to stay conservative if per-user command menus are not available in the current library version; `/help` must still be role-aware.

### Lane subscription service
Add CRUD around `lane_subscriptions`:
- create/enable subscription for caller's lane
- disable subscription for caller's lane
- list caller's subscriptions
- resolve channels through existing channel sync/discovery code

### Lane poller
Add a lane-aware poll path:
- iterate due `lane_subscriptions`
- fetch/diff channel uploads using lane-level `last_seen_video_ids`
- create `lane_video_items`
- submit shared processing only when the global video is not already completed or active
- if the global video is already completed, attach it to the lane without duplicating work
- preserve existing long-form filtering and per-poll caps

### Lane digest
Add a lane digest input collector:
- completed lane items in the digest window
- lane-linked active/pending/retrying jobs
- lane-linked failures/manual-review items
- lane subscription count/status
- report delivery status for lane items

Render and send one digest per lane:
- Ken lane digest goes only to Ken's chat
- restricted lane digest goes only to that lane's chat
- admin ops data is not included in personal digests unless a separate ops digest is explicitly added later

### Notifications
Do not send per-video completion/report notifications to restricted users by default. Their first delivery surface should be their lane digest.

## Implementation Chunks
### T049A - Schema and model layer
- Add Alembic migration for `digest_lanes`, `lane_subscriptions`, and `lane_video_items`.
- Add SQLAlchemy models and model/migration contract tests.
- Seed Ken's default lane only if safe and explicit.

### T049B - Lane resolution and command authorization
- Add lane/capability resolution service.
- Split Telegram commands into restricted, personal, and admin surfaces.
- Make `/help` role-aware.
- Reject restricted-user calls to hidden commands.

### T049C - Lane subscription commands
- Rewire `/subscribe`, `/unsubscribe`, and `/subscriptions` to use caller lane.
- Ensure Ken personal use affects Ken lane only, not every lane.
- Add focused Telegram command tests.

### T049D - Lane-aware polling and shared processing attach
- Add lane poller that creates lane items and submits shared processing only when needed.
- Preserve duration filters and caps.
- Avoid duplicate global jobs when a video is already active/completed.
- Add tests for shared-video, active-video, completed-video, and new-video cases.

### T049E - Lane digest renderer and delivery
- Add lane-scoped digest input gathering.
- Add `/digest` and `/lane_digest <lane>` commands.
- Send digest to `digest_lanes.telegram_chat_id`.
- Add tests proving Ken's digest excludes other-lane items and restricted user digest excludes Ken-lane items.

### T049F - Admin monitoring commands
- Add `/lanes`, `/lane_status`, `/lane_failures`, and `/lane_retry`.
- Keep global `/queue` and `/cost` admin-only.
- Add tests around admin-only access.

## Out of Scope
- Full multi-tenant database isolation.
- Separate Docker/Postgres/Redis instances per user.
- Web UI authentication for multiple users.
- Letting restricted users search, ask questions, browse transcripts, retry jobs, toggle RAG, manage notifications, or access admin reports.
- Per-video completion notifications to restricted users.
- Exposing raw transcript/report artifacts directly to restricted users outside the digest flow.

## Constraints
- Do not begin implementation until the current catch-up pipeline has fully completed.
- Preserve existing Ken/admin workflows unless explicitly replaced.
- Keep the initial restricted user surface small and boring.
- Existing global processing data may remain shared; recipient-facing delivery and configuration must be lane-scoped.
- Build must use repo-native artifacts as source of truth: `docs/PLAN.md`, `docs/CLARIFICATIONS.md`, `docs/tasks/TASK_INDEX.md`, and this task file.

## Done Criteria
- Restricted lane user can add, remove, and list only their own lane channels.
- Restricted lane user receives only their own digest.
- Restricted lane user cannot use search, chat, queue, retry, RAG, notification, report, or admin commands.
- Ken's personal digest contains only Ken-lane content.
- Ken can monitor and troubleshoot all lanes through admin commands.
- Lane poller attaches existing completed/active global videos to a lane without duplicating work.
- Lane digest tests prove cross-lane content does not leak into recipient digests.
- Existing owner/operator tests remain green.

## Validation
- Alembic/model contract tests for new tables and constraints.
- Focused service tests for lane subscription CRUD and lane poller behavior.
- Telegram command tests for restricted vs admin authorization.
- Digest tests for lane scoping and delivery target.
- Existing subscription and digest tests updated without broad regressions.
- QAClaw validates against this task file after implementation.

## Blocked Until
- Current YouTube catch-up pipeline reaches zero active jobs and no new blocker state.
- Ken explicitly approves starting implementation.

## Notes
- Related context: `docs/CLARIFICATIONS.md`, `docs/tasks/T048_subscription_watchlist_longform.md`.
- The initial production lane setup will need the other recipient's Telegram user ID/chat ID.
