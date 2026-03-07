# Channel Video Filtering Feature

## Goal
Add server-side filtering to channel video discovery (limit, date range, duration) and a "latest N" convenience for the process endpoint.

## Assumptions
- yt-dlp DateRange expects YYYYMMDD format (no dashes) -- dates converted automatically
- yt-dlp `playlistend` limits results (newest first by default)
- yt-dlp `match_filter` handles duration filtering
- Telegram bot has no channel module dependencies (verified)
- Pre-existing collection error (test_telegram_bot.py: telegram module not installed) unrelated

## Steps
1. Add `limit`, `after_date`, `before_date`, `min_duration`, `max_duration` params to `discover_channel_videos()` in `app/services/youtube.py`
2. Update `ChannelSubmit` schema in `app/schemas/video.py` with matching fields
3. Pass filter params through in `submit_channel` endpoint in `app/routers/channels.py`
4. Add `latest: int | None` to `ChannelVideoSelection` schema; update `process_selected_videos` to auto-select latest N videos when `video_ids` is empty
5. Verify Telegram bot has no channel imports (confirmed: no matches)
6. Write comprehensive tests in `tests/test_channel_filters.py`
7. Run full test suite: 630 passed
