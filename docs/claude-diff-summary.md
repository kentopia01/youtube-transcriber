# Channel Video Filtering -- Diff Summary

## What Changed

| File | Change |
|---|---|
| `app/services/youtube.py` | `discover_channel_videos()` accepts 5 new keyword args: limit, after_date, before_date, min_duration, max_duration. Uses yt-dlp playlistend, DateRange (YYYYMMDD), match_filter_func. |
| `app/schemas/video.py` | `ChannelSubmit` extended with 5 optional filter fields. `ChannelVideoSelection.video_ids` default changed to `[]`, added `latest: int | None`. |
| `app/routers/channels.py` | `submit_channel` passes all filter params. `process_selected_videos` queries DB for latest N when `latest` is set and `video_ids` empty. |
| `tests/test_channel_filters.py` | New file: 14 tests covering yt-dlp option passing, API filter forwarding, latest-N processing. |
| `docs/claude-plan.md` | Updated for this feature. |
| `docs/claude-test-results.txt` | Updated with test output. |

## Why
Users needed server-side filtering to avoid fetching all channel videos.

## Risks
- `video_ids` default changed from required to `[]` -- callers sending neither `video_ids` nor `latest` get 400.
- DateRange with only start or only end relies on yt-dlp defaults (verified).

## No deviations from plan.
