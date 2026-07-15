# T048 - Subscription Watchlist and Long-Form Ingest

## Objective

Update the active YouTube subscription watchlist requested by Ken and ensure autonomous channel polling downloads long-form videos only.

## In Scope

- Keep My First Million active.
- Add or re-enable:
  - Andrej Karpathy
  - Sweat Equity
  - Lenny's Podcast
  - Oren Meets World
- Seed Andrej Karpathy's 30 most recent long-form videos.
- Filter subscription auto-ingest/backlog seeding away from Shorts, reels, and short clips.
- Document the filter setting and validate focused tests.

## Out of Scope

- Changing manual single-video submission behavior.
- Raising the global maximum video duration cap.
- Redesigning subscription UI.
- Regenerating old summaries unrelated to the new subscriptions.

## Done Criteria

- Active subscription rows reflect the requested watchlist additions.
- Subscription auto-ingest rejects videos below `AUTO_INGEST_MIN_DURATION_SECONDS` by default.
- Focused classifier/subscription tests pass.
- Runtime is restarted or otherwise reloaded so the new filter is active.
- Andrej Karpathy long-form backlog queueing is verified.

## Result

- Enabled subscriptions:
  - Andrej Karpathy
  - Oren Meets World
  - Sweat Equity
  - Lenny's Podcast
  - My First Million remained active
- Active subscriptions now total 11, all at 24h cadence and `max_videos_per_poll=3`.
- Added `AUTO_INGEST_MIN_DURATION_SECONDS` with a default of 600 seconds.
- Seeded Andrej Karpathy's long-form backlog:
  - 13 videos in the recent window matched the 10-minute floor.
  - 11 were under the current `MAX_VIDEO_DURATION_MINUTES=150` cap and were queued.
  - 2 were intentionally skipped because they exceed the current cap:
    - `7xTGNNLPyMI` - Deep Dive into LLMs like ChatGPT
    - `l8pRSuU81PU` - Let's reproduce GPT-2 (124M)
- Released the first Andrej job (`EWvNQjAaOHw` - How I use LLMs) to the queue; remaining Andrej jobs are pending behind dispatcher fairness.

## Validation

- `python -m pytest tests/test_video_classifier.py tests/test_poll_subscriptions.py tests/test_subscriptions_api.py tests/test_channel_filters.py tests/test_config.py -q` -> `95 passed`
- `git diff --check` -> clean
- Web container restarted and served `/` successfully.
- Native workers were not restarted while active jobs were running; the subscription cron uses a fresh Python process and will load the new filter on its next run.

## Rollback

- Disable any newly added subscription row through `/api/subscriptions/{id}` or DB patch.
- Set `AUTO_INGEST_MIN_DURATION_SECONDS=0` to temporarily disable the long-form floor.
