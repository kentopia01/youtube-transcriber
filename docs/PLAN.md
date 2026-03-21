# Channel Video Filtering Feature

## Goal
Add server-side filtering to channel video discovery and processing so users can limit ingestion by recency (latest N), date range, and duration — instead of fetching all videos and filtering client-side. Also ensure the Telegram bot has no dependency gaps related to channel features.

## Current State
- `discover_channel_videos()` in `app/services/youtube.py` returns ALL videos from a channel via yt-dlp `extract_flat`
- `POST /api/channels` calls discover and returns the full list; user then selects via `POST /api/channels/{id}/process`
- No server-side filtering params exist
- Duplicate detection is solid (get-or-create by `youtube_video_id` + pipeline smart retry)
- Telegram bot (`app/telegram_bot.py`) is chat-focused — no channel ingestion commands; check if it imports/depends on channel features

## Tasks

### Task 1: Add filtering params to `discover_channel_videos()`
**File:** `app/services/youtube.py`

Add optional params to `discover_channel_videos()`:
- `limit: int | None = None` — return only the N most recent videos
- `after_date: str | None = None` — only videos published after this date (YYYY-MM-DD)
- `before_date: str | None = None` — only videos published before this date
- `min_duration: int | None = None` — minimum duration in seconds
- `max_duration: int | None = None` — maximum duration in seconds

yt-dlp `extract_flat` doesn't return `upload_date` per entry reliably, so:
- Use yt-dlp's `daterange` and `match_filter` options where possible
- For `limit`, use yt-dlp's `playlistend` option (videos are returned newest-first by default)
- For duration filters, use yt-dlp's `match_filter` with duration range
- For date filters, use yt-dlp's `daterange` option

### Task 2: Add filter params to channel API endpoint
**File:** `app/routers/channels.py`, `app/schemas/video.py`

Update `ChannelSubmit` schema:
```python
class ChannelSubmit(BaseModel):
    url: str
    limit: int | None = None           # latest N videos
    after_date: str | None = None       # YYYY-MM-DD
    before_date: str | None = None      # YYYY-MM-DD
    min_duration: int | None = None     # seconds
    max_duration: int | None = None     # seconds
```

Pass these through to `discover_channel_videos()` in the `submit_channel` endpoint.

### Task 3: Add "process latest N" convenience on process endpoint
**File:** `app/routers/channels.py`

Update `ChannelVideoSelection` to optionally accept `latest: int` as an alternative to explicit `video_ids`. If `latest` is set and `video_ids` is empty, auto-select the N most recent discovered videos for that channel.

### Task 4: Telegram bot dependency check
**File:** `app/telegram_bot.py`

- Verify the Telegram bot doesn't break from any channel router changes
- Check if it has any direct imports from channel modules
- If it references channel features, ensure compatibility
- Confirm bot tests still pass

### Task 5: Tests
- Unit tests for `discover_channel_videos()` with filter params (mock yt-dlp)
- API tests for `POST /api/channels` with filter params
- API tests for `POST /api/channels/{id}/process` with `latest` param
- Ensure all existing tests still pass (301+ collected)

## Tech Notes
- Python 3.14 venv at `.venv314/`
- Run tests: `.venv314/bin/python -m pytest tests/ -x -q`
- 301 tests currently collected (10 collection errors pre-existing — ignore those)
- Do NOT modify Docker config or worker code — this is API/service layer only
- Commit to `main` branch when done
