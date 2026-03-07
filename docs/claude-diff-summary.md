# QAClaw: Channel Filtering QA Fixes -- Diff Summary

## What Changed

| File | Change |
|---|---|
| `app/schemas/video.py` | Added Pydantic `field_validator` for: `limit` (>= 1), `after_date`/`before_date` (YYYY-MM-DD regex), `min_duration`/`max_duration` (>= 0), `latest` (>= 1). |
| `tests/test_channel_filters.py` | Added 6 edge-case validation tests: limit=0, limit=-5, invalid date format, negative duration, latest=0, latest=-1. |

## Why
The original implementation had no input validation on filter parameters. Invalid values (limit=0, negative durations, malformed dates) would either silently produce unexpected results or crash inside yt-dlp at runtime.

## Risks
- `limit=0` is now rejected (422) instead of silently returning no results. Unlikely to break existing callers.
- Date validation is regex-only (YYYY-MM-DD format) -- does not check if the date is actually valid (e.g., 2024-02-30 passes). yt-dlp's DateRange handles this gracefully.

## Known Limitations (not bugs)
- `daterange` filter with `extract_flat: True` may not apply when yt-dlp doesn't have `upload_date` in flat playlist entries. The date filter works best when yt-dlp can resolve per-video upload dates.
- `test_telegram_bot.py` is skipped because `telegram` module is not installed in `.venv314`.
