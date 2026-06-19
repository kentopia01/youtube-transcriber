# T028 - yt-dlp Cookie 403 Fallback

## Status
Done

## Objective
Recover public-video downloads when the configured YouTube cookie file routes yt-dlp into a 403 media-download path.

## Why it matters
The 2026-06-19 auto-ingest failed seven videos at the download stage. A direct probe showed the same video fails with the configured cookie file but downloads successfully without cookies.

## Scope
- Retry the audio download once without cookies after a cookie-backed yt-dlp 403.
- Keep existing cookie behavior as the first attempt.
- Add focused unit coverage for the fallback boundary.

## Out of scope
- Reworking subscription polling.
- Adding PO-token generation.
- Retrying the seven failed production jobs automatically.
- Updating yt-dlp in the production virtualenv.

## Constraints
- Keep the change isolated to the YouTube download path.
- Do not mask non-403 yt-dlp errors.
- Do not retry without cookies when cookies were not used.

## Done criteria
- Cookie-backed 403 retries once without cookies.
- Non-403 download errors still fail normally.
- No-cookie 403 still fails normally.
- Focused tests pass.

## Validation
- Main-session implementation against this file.
- Focused pytest coverage for `app.services.youtube.download_audio`.

## Notes
- Related upstream yt-dlp signal: YouTube SABR/PO-token behavior can remove or block normal media URLs for some sessions.
