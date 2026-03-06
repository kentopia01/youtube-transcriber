# Phase 1: Chat Toggle System — Diff Summary

## What Changed

| File | Change |
|---|---|
| `app/models/video.py` | Added `chat_enabled` Boolean column (server_default true) |
| `app/models/channel.py` | Added `chat_enabled` Boolean column (server_default true) |
| `alembic/versions/005_add_chat_enabled.py` | **New** — migration adds chat_enabled to both tables |
| `app/schemas/video.py` | Added `ChatToggle` Pydantic schema |
| `app/routers/videos.py` | Added `PATCH /{video_id}/chat-toggle` endpoint |
| `app/routers/channels.py` | Added `PATCH /{channel_id}/chat-toggle` endpoint (bulk-updates all channel videos) |
| `app/services/search.py` | `_build_where_clause` now accepts `chat_enabled_only`; all search functions and dispatcher pass it through |
| `app/templates/library.html` | Video cards wrapped in `.video-card-wrapper` with toggle switch; channel cards wrapped similarly; JS for dimming |
| `app/static/css/main.css` | Added section 31: chat toggle switch styles, `.is-chat-disabled` opacity dimming |
| `tests/test_chat_toggle.py` | **New** — 14 tests covering toggle API, channel bulk update, search filter |

## Why
Phase 1 of Chat with Transcripts feature — users need to control which videos are included in chat context via toggles.

## Risks
- Channel toggle iterates all videos in Python (no bulk SQL UPDATE). Fine for typical channel sizes (<500 videos), but could be slow for very large channels.
- HTMX toggle sends PATCH with `hx-vals='js:...'` which requires JS evaluation — won't work if JS is disabled.

## Plan Deviations
- None. All planned steps completed as specified.
